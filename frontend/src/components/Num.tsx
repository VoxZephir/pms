/** A figure that rolls to its new value when the period changes -- the eye
 * follows the change instead of re-reading a number that simply swapped. */
import { animate, useReducedMotion } from "motion/react";
import { useEffect, useRef } from "react";

import { chf } from "@/lib/format";

export function Num({
  value, decimals = 0, format, className,
}: {
  value: number;
  decimals?: number;
  format?: (v: number) => string;
  className?: string;
}) {
  const ref = useRef<HTMLSpanElement>(null);
  const previous = useRef(value);
  const reduce = useReducedMotion();
  const render = format ?? ((v: number) => chf(v, decimals));

  useEffect(() => {
    const node = ref.current;
    if (!node) return;
    const from = previous.current;
    previous.current = value;
    if (reduce || from === value) {
      node.textContent = render(value);
      return;
    }
    const controls = animate(from, value, {
      duration: 0.55,
      ease: [0.2, 0.8, 0.2, 1],
      onUpdate: (v) => { node.textContent = render(v); },
    });
    return () => controls.stop();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value, reduce]);

  return <span ref={ref} className={className}>{render(value)}</span>;
}
