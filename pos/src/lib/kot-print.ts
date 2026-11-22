import { call } from '@ury/core';

interface KotPrintPayload {
  html: string | null;
  kot_names: string[];
  print_format: string;
}

interface PrintKotSlipParams {
  invoiceId: string;
  kotNames: string[];
}

/**
 * Only one slip can be on screen at a time. Holding the frame lets a fast
 * second send replace a stale slip instead of stacking hidden frames.
 */
let activeFrame: HTMLIFrameElement | null = null;

const CLEANUP_FALLBACK_MS = 60_000;

function cleanupFrame(frame: HTMLIFrameElement) {
  frame.remove();
  if (activeFrame === frame) {
    activeFrame = null;
  }
}

/**
 * Default the browser's page size to an 80mm slip. This is a browser-only
 * suggestion: the Print Format in Desk still owns the slip's content and
 * styling, so an edit there is reflected without a rebuild.
 */
function withSlipPageSize(html: string): string {
  const style = '<style>@page { size: 80mm auto; margin: 3mm; }</style>';
  return html.includes('</head>')
    ? html.replace('</head>', `${style}</head>`)
    : `${style}${html}`;
}

/**
 * Print the combined KOT slip for the delta KOTs a send just created.
 *
 * The slip is rendered by the server from the `URY KOT` print format Desk
 * resolves (default print format, else `URY Waiter Order Slip`), so any format
 * change made in Desk is used on the next send. This path never touches
 * `POS Invoice.invoice_printed` — printing the bill is what moves an order to
 * Unbilled, and a KOT must not.
 *
 * Returns false on failure instead of throwing: the order is already saved,
 * so a missing slip must never surface as a failed send.
 */
export async function printKotSlip({
  invoiceId,
  kotNames,
}: PrintKotSlipParams): Promise<boolean> {
  if (!invoiceId || kotNames.length === 0) {
    return false;
  }

  try {
    const response = await call.get<{ message: KotPrintPayload }>(
      'ury.ury.api.ury_waiter_print.get_combined_kot_print_html',
      {
        invoice: invoiceId,
        kot_names: JSON.stringify(kotNames),
      }
    );

    const payload = response.message;
    if (!payload?.html) {
      console.warn('KOT slip has no HTML; skipping browser print.', payload);
      return false;
    }

    if (activeFrame) {
      cleanupFrame(activeFrame);
    }

    const frame = document.createElement('iframe');
    frame.setAttribute('aria-hidden', 'true');
    frame.style.cssText =
      'position:fixed;width:0;height:0;border:0;left:-9999px;top:-9999px;';
    activeFrame = frame;

    frame.onload = () => {
      const frameWindow = frame.contentWindow;
      if (!frameWindow) {
        cleanupFrame(frame);
        return;
      }

      // Browsers disagree about whether print() blocks. afterprint is the
      // normal signal; the timeout is the fallback for frames that never
      // emit it.
      const cleanupTimer = window.setTimeout(
        () => cleanupFrame(frame),
        CLEANUP_FALLBACK_MS
      );
      frameWindow.addEventListener(
        'afterprint',
        () => {
          window.clearTimeout(cleanupTimer);
          cleanupFrame(frame);
        },
        { once: true }
      );

      try {
        frameWindow.focus();
        frameWindow.print();
      } catch (error) {
        console.error('KOT print dialog failed:', error);
        window.clearTimeout(cleanupTimer);
        cleanupFrame(frame);
      }
    };

    frame.srcdoc = withSlipPageSize(payload.html);
    document.body.appendChild(frame);
    return true;
  } catch (error) {
    console.error('KOT slip could not be printed:', error);
    return false;
  }
}
