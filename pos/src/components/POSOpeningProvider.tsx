import { useCallback, useEffect, useMemo, useState } from 'react';
import { canBill as canBillUser } from '../lib/billing';
import {
  parseFrappeError,
  validatePOSClose,
  POSOpeningEntryRef,
} from '../lib/pos-opening-api';
import { getOpenPosOpeningEntries } from '../lib/pos-closing-api';
import { getChecklist } from '../lib/checklist-api';
import { usePOSStore } from '../store/pos-store';
import { useRootStore } from '../store/root-store';
import { User } from '../store/slices/auth-slice';
import POSOpeningDialog from './POSOpeningDialog';
import POSOpeningScreen from './POSOpeningScreen';
import ChecklistGateDialog from './ChecklistGateDialog';
import POSClosingDialog from './POSClosingDialog';
import { t } from '../i18n';

/**
 * Shift gate: no open shift for the branch means no POS screen, for anyone.
 *
 * Gating is deliberately NOT route-aware. An earlier version exempted
 * "non-transactional" routes (dashboard, settings) so they could render
 * without a shift; that invited exactly the confusion this gate exists to
 * prevent — a cashier wandering the app with no shift open. Privileged
 * users still get the open-shift form, captains get a waiting screen, but
 * nobody sees an app screen until the branch has a shift.
 *
 * Captains are routed to /order (and out of the cashier shell) by
 * `AppLayout`, so "allowed pages for captains" is a routing rule that
 * applies once the shift is open, never a way past this gate.
 *
 * Single-shift only: the branch's first open entry IS the shift, regardless
 * of POS Profile `custom_enable_multiple_cashier`. That flag must stay OFF;
 * re-enabling multi-cashier requires restoring the per-user check here.
 */
interface POSOpeningProviderProps {
  children: React.ReactNode;
}

export type OpeningBlockingState =
  | 'permissionDenied'
  | 'dailyClosePending'
  | 'mainCashierNotOpen'
  | 'crossCompanyOpen'
  | 'genericError';

const DESK_ROLES = ['System Manager', 'Desk User'];

function hasDeskAccess(user: User | null): boolean {
  if (!user) return false;
  if (user.name === 'Administrator') return true;
  return user.roles.some((role) => DESK_ROLES.includes(role));
}

function getHttpStatus(error: unknown): number | undefined {
  if (!error || typeof error !== 'object') return undefined;
  const e = error as Record<string, unknown>;
  if (typeof e.httpStatus === 'number') return e.httpStatus;
  if (typeof e.status === 'number') return e.status;
  if (typeof e.statusCode === 'number') return e.statusCode;
  return undefined;
}

const POSOpeningProvider = ({ children }: POSOpeningProviderProps) => {
  const [isLoading, setIsLoading] = useState(true);
  const [blockingState, setBlockingState] = useState<OpeningBlockingState | null>(null);
  const [blockingMessage, setBlockingMessage] = useState<string>('');
  const [existingEntry, setExistingEntry] = useState<POSOpeningEntryRef | null>(null);
  // True when the branch has an open shift (single-shift model) — not when
  // the session user has one of their own.
  const [shiftOpen, setShiftOpen] = useState(false);
  // Set once checkPOSStatus() confirms the POS is open but today's Opening
  // checklist log isn't status="Complete" yet. Takes priority over the
  // daily-close check below -- the cashier must clear the checklist before
  // we even look at whether a previous session needs closing.
  const [needsOpeningChecklist, setNeedsOpeningChecklist] = useState(false);
  // True once the cashier taps "Close Now" from the dailyClosePending
  // blocking dialog -- renders the real POSClosingDialog instead of just
  // telling them to contact a manager.
  const [showClosingDialog, setShowClosingDialog] = useState(false);

  const { posProfile, showVoluntaryClosing, setShowVoluntaryClosing } = usePOSStore();
  const { user } = useRootStore();

  const canAccessDesk = useMemo(() => hasDeskAccess(user), [user]);

  // Billing user = holds a role listed in the POS Profile's "Role Allowed
  // For Billing" (plus the admin exemption). Only they may open/close a
  // shift; captains never do.
  const canBill = useMemo(() => canBillUser(user, posProfile), [user, posProfile]);

  const clearBlockingState = useCallback(() => {
    setBlockingState(null);
    setBlockingMessage('');
    setShowClosingDialog(false);
  }, []);

  const handleScreenError = useCallback(
    (state: OpeningBlockingState, message?: string) => {
      setBlockingState(state);
      setBlockingMessage(message || '');
    },
    []
  );

  const checkPOSStatus = useCallback(async () => {
    if (!posProfile) return;

    setIsLoading(true);
    clearBlockingState();
    setExistingEntry(null);
    setShiftOpen(false);
    setNeedsOpeningChecklist(false);

    try {
      // Single-shift model: the shift belongs to the branch, not to the
      // session user. Captains and joiners work under whatever shift the
      // branch has open; only billing users can open/close one.
      const entries = await getOpenPosOpeningEntries(posProfile.name);
      const shift = entries?.[0] ?? null;

      setShiftOpen(Boolean(shift));
      setExistingEntry(shift);

      // Opening checklist + daily-close only concern the cashier/manager
      // who opens or works the shift. Captains are never sent through them.
      if (canBill && posProfile.name) {
        try {
          const { logStatus } = await getChecklist(posProfile.name, 'Opening');
          if (logStatus !== 'Complete') {
            setNeedsOpeningChecklist(true);
            setIsLoading(false);
            return;
          }
        } catch (error) {
          console.error('Failed to check opening checklist status:', error);
          // On error, block on the checklist for safety.
          setNeedsOpeningChecklist(true);
          setIsLoading(false);
          return;
        }

        if (posProfile.custom_daily_pos_close === 1) {
          const closeResponse = await validatePOSClose(posProfile.name);
          if (closeResponse.message === 'Failed') {
            setBlockingState('dailyClosePending');
            setIsLoading(false);
            return;
          }
        }
      }

      setIsLoading(false);
    } catch (error) {
      console.error('Failed to check POS opening status:', error);

      const serverMessage = parseFrappeError(error);
      const status = getHttpStatus(error);
      const fallbackMessage =
        error instanceof Error ? error.message : t('errors.posOpening.load_failed');
      const message = serverMessage || fallbackMessage;

      if (status === 403 || /permission/i.test(message)) {
        setBlockingState('permissionDenied');
      } else if (/main cashier/i.test(message)) {
        setBlockingState('mainCashierNotOpen');
        setBlockingMessage(message);
      } else {
        setBlockingState('genericError');
        setBlockingMessage(message);
      }

      setIsLoading(false);
    }
  }, [posProfile, canBill, clearBlockingState]);

  const handleOpeningSuccess = useCallback(() => {
    clearBlockingState();
    checkPOSStatus();
  }, [clearBlockingState, checkPOSStatus]);

  const handleClosingSuccess = useCallback(() => {
    clearBlockingState();
    checkPOSStatus();
  }, [clearBlockingState, checkPOSStatus]);

  useEffect(() => {
    if (posProfile) {
      checkPOSStatus();
    }
  }, [posProfile, checkPOSStatus]);

  const voluntaryClosing = showVoluntaryClosing ? (
    <POSClosingDialog
      open={showVoluntaryClosing}
      onOpenChange={(open) => {
        if (!open) setShowVoluntaryClosing(false);
      }}
      onClosingSubmitted={() => {
        setShowVoluntaryClosing(false);
        checkPOSStatus();
      }}
    />
  ) : null;

  if (isLoading) {
    return (
      <div className="fixed inset-0 bg-white flex items-center justify-center z-50">
        <div className="text-center">
          <div className="animate-spin rounded-full h-12 w-12 border-b-2 border-blue-600 mx-auto mb-4"></div>
          <p className="text-gray-600">{t('common.checking_pos_status')}</p>
        </div>
      </div>
    );
  }

  if (showClosingDialog && posProfile) {
    return (
      <POSClosingDialog
        open={showClosingDialog}
        onOpenChange={(open) => {
          if (!open) setShowClosingDialog(false);
        }}
        onClosingSubmitted={handleClosingSuccess}
      />
    );
  }

  if (blockingState) {
    return (
      <POSOpeningDialog
        state={blockingState}
        message={blockingMessage}
        existingEntry={existingEntry}
        canAccessDesk={canAccessDesk}
        onRetry={checkPOSStatus}
        onContinue={() => setBlockingState(null)}
        onCloseNow={
          blockingState === 'dailyClosePending'
            ? () => setShowClosingDialog(true)
            : undefined
        }
      />
    );
  }

  // Block on the Opening checklist until it's submitted as Complete.
  if (needsOpeningChecklist && posProfile?.name) {
    return (
      <ChecklistGateDialog
        posProfile={posProfile.name}
        checklistType="Opening"
        onComplete={() => {
          setNeedsOpeningChecklist(false);
          checkPOSStatus();
        }}
      />
    );
  }

  if (!shiftOpen) {
    // Captains never open shifts: if the branch has no shift, they wait.
    if (!canBill) {
      return <ShiftWaitingScreen onRetry={checkPOSStatus} />;
    }
    return (
      <POSOpeningScreen
        onSuccess={handleOpeningSuccess}
        onError={handleScreenError}
      />
    );
  }

  return (
    <>
      {children}
      {voluntaryClosing}
    </>
  );
};

/**
 * Shown to non-billing users (captains) when the branch has no open shift.
 * They cannot open one — they wait for the cashier or manager.
 */
const ShiftWaitingScreen = ({ onRetry }: { onRetry: () => void }) => (
  <div className="fixed inset-0 bg-white flex items-center justify-center z-50 px-6">
    <div className="text-center max-w-sm">
      <div className="text-4xl mb-3">🔒</div>
      <h2 className="text-xl font-semibold text-gray-800 mb-2">
        {t('pos_opening.shift_not_open_title')}
      </h2>
      <p className="text-gray-600 mb-6">{t('pos_opening.shift_not_open_body')}</p>
      <button
        type="button"
        onClick={onRetry}
        className="px-4 py-2 rounded-lg bg-blue-600 text-white font-medium"
      >
        {t('pos_opening.retry')}
      </button>
    </div>
  </div>
);

export default POSOpeningProvider;
