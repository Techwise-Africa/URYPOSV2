import { derivePOSCapabilities } from '@ury/core';
import type { PosProfileCombined, User } from '@ury/core';

/**
 * True if the user may bill, discount, cancel and open/close a shift.
 *
 * Mirrors `derivePOSCapabilities().canSettlePayment` (roles listed in the
 * POS Profile's "Role Allowed For Billing") plus the server-side admin
 * exemption used by `_order_ownership_flags()`: Administrator and System
 * Manager act as billing users even though they are not in that list.
 */
export function canBill(
  user: User | null,
  posProfile: PosProfileCombined | null
): boolean {
  if (!user) return false;
  if (user.name === 'Administrator' || user.roles?.includes('System Manager')) {
    return true;
  }
  if (!posProfile) return false;
  return derivePOSCapabilities(user, posProfile).canSettlePayment;
}
