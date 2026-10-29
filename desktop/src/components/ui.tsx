import { useId, type ComponentProps, type ReactNode } from "react";

import { cn } from "../lib/utils";
import { Button as ButtonControl, InlineButton } from "./primitives/button";
import { Input as InputControl } from "./primitives/input";
import { Switch as SwitchControl } from "./primitives/switch";
import { Textarea as TextareaControl } from "./primitives/textarea";

export { Confirm } from "./confirm";
export { Picker } from "./picker";
export { SettingsDisclosure } from "./settings-disclosure";

const variants = {
  default: "outline",
  primary: "default",
  ghost: "ghost",
} as const;

export function Button({
  variant = "default",
  className,
  type = "button",
  loading = false,
  children,
  ...props
}: ComponentProps<"button"> & {
  variant?: keyof typeof variants | "text";
  loading?: boolean;
}) {
  const buttonProps = {
    ...props,
    disabled: props.disabled || loading,
    "aria-busy": loading,
    type,
  };
  const content = <>{loading && <span className="button-spinner" aria-hidden="true" />}{children}</>;

  if (variant === "text") {
    return <InlineButton {...buttonProps} className={cn("text-button", className)}>{content}</InlineButton>;
  }

  return (
    <ButtonControl
      {...buttonProps}
      variant={variants[variant]}
      className={cn("button", variant !== "default" && variant, className)}
    >{content}</ButtonControl>
  );
}

export function Input({
  className,
  shellClassName,
  unstyled = false,
  ...props
}: ComponentProps<"input"> & { shellClassName?: string; unstyled?: boolean }) {
  return <InputControl {...props} nativeInput unstyled={unstyled} className={cn("control", shellClassName)} inputClassName={className} />;
}

export function TextArea({
  className,
  shellClassName,
  ...props
}: ComponentProps<"textarea"> & { shellClassName?: string }) {
  return <TextareaControl {...props} className={cn("control", shellClassName)} textareaClassName={className} />;
}

type RowProps = {
  title: string;
  hint?: string;
  children: ReactNode;
  htmlFor?: string;
  hintId?: string;
};

export function Row({ title, hint, children, htmlFor, hintId }: RowProps) {
  return (
    <div className="row" data-slot="settings-row">
      <div className="row-layout">
        <div className="row-label">
          <h3 className="row-title">
            {htmlFor ? <label htmlFor={htmlFor}>{title}</label> : title}
          </h3>
          {hint && <p id={hintId}>{hint}</p>}
        </div>
        <div className="row-control">{children}</div>
      </div>
    </div>
  );
}

export function Field({
  title,
  hint,
  id: suppliedId,
  ...props
}: ComponentProps<"input"> & { title: string; hint?: string }) {
  const generatedId = useId();
  const id = suppliedId ?? generatedId;
  const hintId = hint ? `${id}-hint` : undefined;
  const description =
    [props["aria-describedby"], hintId].filter(Boolean).join(" ") || undefined;
  return (
    <Row title={title} hint={hint} htmlFor={id} hintId={hintId}>
      <Input {...props} id={id} aria-describedby={description} />
    </Row>
  );
}

export function Switch({
  label,
  onChange,
  className,
  ...props
}: Omit<ComponentProps<typeof SwitchControl>, "onCheckedChange"> & {
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <SwitchControl
      {...props}
      nativeButton
      render={<button type="button" />}
      className={cn("switch", className)}
      aria-label={label}
      onCheckedChange={onChange}
    />
  );
}

export function Toggle({
  title,
  hint,
  checked,
  onChange,
}: {
  title: string;
  hint?: string;
  checked: boolean;
  onChange: (checked: boolean) => void;
}) {
  const id = useId();
  const hintId = hint ? `${id}-hint` : undefined;
  return (
    <Row title={title} hint={hint} htmlFor={id} hintId={hintId}>
      <Switch
        id={id}
        label={title}
        aria-describedby={hintId}
        checked={checked}
        onChange={onChange}
      />
    </Row>
  );
}

export function Section({
  title,
  id,
  children,
  className,
}: {
  title?: ReactNode;
  id?: string;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section id={id} className={cn("settings-section", className)} data-slot="settings-section">
      {title && <h2>{title}</h2>}
      <div className="section-content" data-slot="settings-group">{children}</div>
    </section>
  );
}
