import {
  useId,
  type ButtonHTMLAttributes,
  type InputHTMLAttributes,
  type ReactNode,
  type TextareaHTMLAttributes,
} from "react";
import * as Dialog from "@radix-ui/react-dialog";
import * as RadixSwitch from "@radix-ui/react-switch";
import { X } from "lucide-react";

export { Picker } from "./picker";

const variants = {
  default: "button",
  primary: "button primary",
  ghost: "button ghost",
  text: "text-button",
};

export function Button({
  variant = "default",
  className = "",
  type = "button",
  ...props
}: ButtonHTMLAttributes<HTMLButtonElement> & {
  variant?: keyof typeof variants;
}) {
  return (
    <button
      {...props}
      type={type}
      className={`${variants[variant]} ${className}`.trim()}
    />
  );
}

export function Input({
  className = "",
  ...props
}: InputHTMLAttributes<HTMLInputElement>) {
  return <input {...props} className={`control ${className}`.trim()} />;
}

export function TextArea({
  className = "",
  ...props
}: TextareaHTMLAttributes<HTMLTextAreaElement>) {
  return <textarea {...props} className={`control ${className}`.trim()} />;
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
    <div className="row">
      <div className="row-label">
        {htmlFor ? (
          <label htmlFor={htmlFor}>{title}</label>
        ) : (
          <div>{title}</div>
        )}
        {hint && <p id={hintId}>{hint}</p>}
      </div>
      <div className="row-control">{children}</div>
    </div>
  );
}

export function Field({
  title,
  hint,
  id: suppliedId,
  ...props
}: InputHTMLAttributes<HTMLInputElement> & { title: string; hint?: string }) {
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
  ...props
}: Omit<RadixSwitch.SwitchProps, "onChange"> & {
  label: string;
  onChange: (checked: boolean) => void;
}) {
  return (
    <RadixSwitch.Root
      {...props}
      className="switch"
      aria-label={label}
      onCheckedChange={onChange}
    >
      <RadixSwitch.Thumb className="switch-thumb" />
    </RadixSwitch.Root>
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
    <div className="row">
      <div className="row-label">
        <label htmlFor={id}>{title}</label>
        {hint && <p id={hintId}>{hint}</p>}
      </div>
      <Switch
        id={id}
        label={title}
        aria-describedby={hintId}
        checked={checked}
        onChange={onChange}
      />
    </div>
  );
}

export function Section({
  title,
  children,
  className,
}: {
  title?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={className}>
      {title && <h2>{title}</h2>}
      {children}
    </section>
  );
}

export function Confirm({
  open,
  title,
  description,
  children,
  onOpenChange,
}: {
  open: boolean;
  title: string;
  description: string;
  children: ReactNode;
  onOpenChange: (open: boolean) => void;
}) {
  return (
    <Dialog.Root open={open} onOpenChange={onOpenChange}>
      <Dialog.Portal>
        <Dialog.Overlay className="dialog-overlay" />
        <Dialog.Content className="dialog">
          <Dialog.Title>{title}</Dialog.Title>
          <Dialog.Description>{description}</Dialog.Description>
          <Dialog.Close
            className="icon-button dialog-close"
            aria-label="Fechar"
          >
            <X size={18} />
          </Dialog.Close>
          <div className="dialog-actions">{children}</div>
        </Dialog.Content>
      </Dialog.Portal>
    </Dialog.Root>
  );
}
