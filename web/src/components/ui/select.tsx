import * as React from "react";
import * as SelectPrimitive from "@radix-ui/react-select";
import { Check, ChevronDown } from "lucide-react";
import { cn } from "@/lib/utils";

const Select = SelectPrimitive.Root;
const SelectValue = SelectPrimitive.Value;

const SelectTrigger = React.forwardRef<React.ElementRef<typeof SelectPrimitive.Trigger>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Trigger>>(
  ({ className, children, ...props }, ref) => <SelectPrimitive.Trigger ref={ref} className={cn("inline-flex h-8 items-center justify-between gap-1.5 rounded-md border-0 bg-transparent px-2 text-xs font-medium text-foreground outline-none transition-colors hover:bg-accent/10 focus-visible:bg-accent/10 focus-visible:ring-1 focus-visible:ring-ring", className)} {...props}>{children}<SelectPrimitive.Icon asChild><ChevronDown className="select-chevron h-3.5 w-3.5 shrink-0 text-muted-foreground" /></SelectPrimitive.Icon></SelectPrimitive.Trigger>,
);
SelectTrigger.displayName = SelectPrimitive.Trigger.displayName;

const SelectContent = React.forwardRef<React.ElementRef<typeof SelectPrimitive.Content>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Content>>(
  ({ className, children, ...props }, ref) => <SelectPrimitive.Portal><SelectPrimitive.Content ref={ref} position="popper" sideOffset={4} className={cn("z-50 min-w-[10rem] overflow-hidden rounded-md border border-border bg-popover p-1 text-popover-foreground shadow-xl", className)} {...props}><SelectPrimitive.Viewport>{children}</SelectPrimitive.Viewport></SelectPrimitive.Content></SelectPrimitive.Portal>,
);
SelectContent.displayName = SelectPrimitive.Content.displayName;

const SelectItem = React.forwardRef<React.ElementRef<typeof SelectPrimitive.Item>, React.ComponentPropsWithoutRef<typeof SelectPrimitive.Item>>(
  ({ className, children, ...props }, ref) => <SelectPrimitive.Item ref={ref} className={cn("relative flex h-9 cursor-pointer select-none items-center rounded-sm py-1 pl-3 pr-8 text-xs outline-none data-[highlighted]:bg-secondary data-[highlighted]:text-foreground", className)} {...props}><SelectPrimitive.ItemText>{children}</SelectPrimitive.ItemText><SelectPrimitive.ItemIndicator className="absolute right-2"><Check className="h-3.5 w-3.5 text-primary" /></SelectPrimitive.ItemIndicator></SelectPrimitive.Item>,
);
SelectItem.displayName = SelectPrimitive.Item.displayName;

export { Select, SelectContent, SelectItem, SelectTrigger, SelectValue };
