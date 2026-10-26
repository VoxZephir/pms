/** Overlays: a bottom sheet on the phone (thumb reach, swipe to close), a
 * centred dialog on the laptop. One component, so every overlay of the app
 * behaves the same way on each. */
import { X } from "lucide-react";
import { Dialog } from "radix-ui";
import type { ReactNode } from "react";
import { Drawer } from "vaul";

import { useDesktop } from "@/lib/hooks";

import { IconButton, cx } from "./ui";

export function Sheet({
  open, onOpenChange, title, description, children, footer, wide,
}: {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: ReactNode;
  description?: ReactNode;
  children: ReactNode;
  footer?: ReactNode;
  wide?: boolean;
}) {
  const desktop = useDesktop();
  if (desktop) {
    return (
      <Dialog.Root open={open} onOpenChange={onOpenChange}>
        <Dialog.Portal>
          <Dialog.Overlay className="fixed inset-0 z-50 bg-black/30 backdrop-blur-[2px] data-[state=open]:animate-[fade-in_.15s_ease]" />
          <Dialog.Content
            className={cx(
              "fixed left-1/2 top-[8vh] z-50 flex max-h-[84vh] w-[calc(100vw-32px)] -translate-x-1/2 flex-col",
              "rounded-[22px] border border-hairline bg-surface shadow-pop outline-none",
              "data-[state=open]:animate-[pop-in_.18s_cubic-bezier(.2,.8,.2,1)]",
              wide ? "max-w-3xl" : "max-w-lg",
            )}
          >
            <div className="flex items-start gap-3 border-b border-hairline px-5 py-4">
              <div className="min-w-0 flex-1">
                <Dialog.Title className="text-[17px] font-semibold tracking-tight">{title}</Dialog.Title>
                {description ? (
                  <Dialog.Description className="mt-0.5 text-[13px] text-muted">{description}</Dialog.Description>
                ) : (
                  <Dialog.Description className="sr-only">{title}</Dialog.Description>
                )}
              </div>
              <Dialog.Close asChild>
                <IconButton label="Fermer" className="-mr-2 -mt-1"><X size={18} /></IconButton>
              </Dialog.Close>
            </div>
            <div className="min-h-0 flex-1 overflow-y-auto px-5 py-4">{children}</div>
            {footer && <div className="border-t border-hairline px-5 py-3">{footer}</div>}
          </Dialog.Content>
        </Dialog.Portal>
      </Dialog.Root>
    );
  }
  return (
    <Drawer.Root open={open} onOpenChange={onOpenChange} repositionInputs={false}>
      <Drawer.Portal>
        <Drawer.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <Drawer.Content
          className="fixed inset-x-0 bottom-0 z-50 flex max-h-[92dvh] flex-col rounded-t-[24px] border-t border-hairline bg-surface outline-none"
        >
          <div aria-hidden className="mx-auto mt-2.5 h-1.5 w-10 shrink-0 rounded-full bg-surface-3" />
          <div className="px-5 pb-2 pt-3">
            <Drawer.Title className="text-[17px] font-semibold tracking-tight">{title}</Drawer.Title>
            {description ? (
              <Drawer.Description className="mt-0.5 text-[13px] text-muted">{description}</Drawer.Description>
            ) : (
              <Drawer.Description className="sr-only">{title}</Drawer.Description>
            )}
          </div>
          <div className="min-h-0 flex-1 overflow-y-auto px-5 pb-4">{children}</div>
          {footer && <div className="border-t border-hairline px-5 py-3">{footer}</div>}
          <div className="safe-b" />
        </Drawer.Content>
      </Drawer.Portal>
    </Drawer.Root>
  );
}
