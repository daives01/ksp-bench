import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

const Select = SelectPrimitive.Root;
const SelectValue = SelectPrimitive.Value;

const SelectTrigger = React.forwardRef<React.ElementRef<typeof SelectPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>>(
  ({ className, children, ...props }, ref) => <SelectPrimitive.Trigger ref={ref} className={cn("inline-flex h-7 items-center justify-between gap-1 border-b border-border bg-transparent px-1 text-[10px] font-medium uppercase tracking-[.06em] text-foreground outline-none transition-colors hover:border-primary focus-visible:border-primary", className)} {...props}>{children}<SelectPrimitive.Icon asChild><ChevronDown className="select-chevron h-3 w-3 shrink-0 text-muted-foreground" /></SelectPrimitive.Icon></SelectPrimitive.Trigger>,
);
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;

const SelectContent = React.forwardRef<React.ElementRef<typeof SelectPrimitive.Content>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>>(
  ({ className, children, ...props }, ref) => <SelectPrimitive.Portal><SelectPrimitive.Content ref={ref} className={cn("z-50 min-w-[8rem] overflow-hidden border border-border bg-popover p-1 text-popover-foreground shadow-xl", className)} {...props}><SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport></SelectPrimitive.Content></SelectPrimitive.Portal>,
);
SelectContent.displayName = SelectPrimitive.Content.displayName;

const SelectItem = React.forwardRef<React.ElementRef<typeof SelectPrimitive.Item>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>>(
  ({ className, children, ...props }, ref) => <SelectPrimitive.Item ref={ref} className={cn("relative flex h-7 cursor-pointer select-none items-center rounded-sm py-1 pl-2 pr-7 text-[10px] uppercase tracking-[.06em] outline-none data-[highlighted]:bg-secondary", className)} {...props}><SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText><SelectPrimitive.ItemIndicator className="absolute right-2"><Check className="h-3 w-3 text-primary" /></SelectPrimitive.ItemIndicator></SelectPrimitive.Item>,
);
SelectItem.displayName = SelectPrimitive.Item.displayName;

export { Select, SelectContent, SelectItem, SelectTrigger, SelectValue };
