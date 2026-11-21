import { Tabs as BaseTabs } from "@base-ui/react/tabs";
import type { ComponentProps } from "react";
import "../../styles/tabs.css";

function Root(props: Omit<ComponentProps<typeof BaseTabs.Root>, "className">) {
  return <BaseTabs.Root {...props} className="segmented-tabs" />;
}

function List(props: Omit<ComponentProps<typeof BaseTabs.List>, "className" | "activateOnFocus">) {
  return <BaseTabs.List {...props} activateOnFocus className="segmented-tabs-list" />;
}

function Tab(props: Omit<ComponentProps<typeof BaseTabs.Tab>, "className">) {
  return <BaseTabs.Tab {...props} className="segmented-tab" />;
}

function Panel(props: Omit<ComponentProps<typeof BaseTabs.Panel>, "className">) {
  return <BaseTabs.Panel {...props} className="segmented-tabs-panel" />;
}

export const SettingsTabs = { Root, List, Tab, Panel };
