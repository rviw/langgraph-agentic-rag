import { CircleAlertIcon } from "lucide-react";
import type { ComponentProps } from "react";

import { cn } from "@/lib/utils";

export function Alert({
  children,
  className,
  ...props
}: ComponentProps<"div">) {
  return (
    <div
      role="alert"
      className={cn(
        "flex min-w-0 items-start gap-2 text-sm text-destructive",
        className,
      )}
      {...props}
    >
      <CircleAlertIcon aria-hidden="true" className="mt-0.5 size-4 shrink-0" />
      <div className="min-w-0 [overflow-wrap:anywhere]">{children}</div>
    </div>
  );
}
