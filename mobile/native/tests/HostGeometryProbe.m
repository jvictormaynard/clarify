// Diagnostic only, compiled into the isolated host, never into the keyboard.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <objc/message.h>

static IMP hostingSizing, itemSizing, layoutSizing, remoteIntrinsic, guideFrame;
static IMP compatFrame, inputSize;
static NSUInteger oversizedFrames;
static NSUInteger eventCount;
static NSMutableDictionary *previous;
static id Read(id object, NSString *key) {
  @try { return [object valueForKey:key]; } @catch (NSException *exception) { return nil; }
}
static NSString *ViewGeometry(UIView *view) {
  if (![view isKindOfClass:UIView.class]) return @"nil";
  return [NSString stringWithFormat:@"%@: frame=%@ intrinsic=%@", NSStringFromClass(view.class),
    NSStringFromCGRect(view.frame), NSStringFromCGSize(view.intrinsicContentSize)];
}
static void Trace(id self, NSString *phase) {
  if (eventCount >= 350) return;
  NSString *message = [NSString stringWithFormat:@"%@ %@ input=[%@] assistant=[%@] accessory=[%@] dock=[%@] inputHeight=%@ assistantHeight=%@",
    phase, NSStringFromClass([self class]), ViewGeometry(Read(self, @"inputView")),
    ViewGeometry(Read(self, @"inputAssistantView")), ViewGeometry(Read(self, @"inputAccessoryView")),
    ViewGeometry(Read(self, @"dockView")), Read(self, @"inputViewHeight"), Read(self, @"assistantHeight")];
  NSString *key = [NSString stringWithFormat:@"%p-%@", self, phase];
  if ([previous[key] isEqualToString:message]) return;
  previous[key] = message; eventCount++;
  NSLog(@"ClarifyHostGeometry %@", message);
}
static void HostingSizing(id self, SEL command) {
  Trace(self, @"hosting-before"); ((void (*)(id,SEL))hostingSizing)(self,command); Trace(self, @"hosting-after");
}
static void ItemSizing(id self, SEL command) {
  Trace(self, @"item-before"); ((void (*)(id,SEL))itemSizing)(self,command); Trace(self, @"item-after");
}
static void LayoutSizing(id self, SEL command) {
  Trace(self, @"layout-before"); ((void (*)(id,SEL))layoutSizing)(self,command); Trace(self, @"layout-after");
}
static CGSize RemoteIntrinsic(id self, SEL command, CGSize size) {
  CGSize result = ((CGSize (*)(id,SEL,CGSize))remoteIntrinsic)(self,command,size);
  if (eventCount < 350) { eventCount++; NSLog(@"ClarifyHostGeometry remote-intrinsic %@ -> %@", NSStringFromCGSize(size), NSStringFromCGSize(result)); }
  return result;
}
static void GuideFrame(id self, SEL command, CGRect frame, BOOL layout) {
  if (frame.size.height > 400 && eventCount < 350) {
    eventCount++; NSLog(@"ClarifyHostGeometry oversized-guide %@ stack=%@", NSStringFromCGRect(frame), NSThread.callStackSymbols);
    id hosting = Read(self, @"hosting");
    for (id item in Read(hosting, @"allHostingItems")) Trace(item, @"oversized-item");
  }
  ((void (*)(id,SEL,CGRect,BOOL))guideFrame)(self,command,frame,layout);
}
static void CompatFrame(id self, SEL command, CGRect frame) {
  if (frame.size.height > 400 && oversizedFrames++ < 12) {
    UIView *view = self;
    NSLog(@"ClarifyHostFrame incoming=%@ before=%@ stack=%@", NSStringFromCGRect(frame), ViewGeometry(view), NSThread.callStackSymbols);
    for (NSUInteger depth = 0; view && depth < 5; depth++, view = view.superview) {
      NSLog(@"ClarifyHostFrame ancestor %lu %@ constraints=%@", (unsigned long)depth, ViewGeometry(view), view.constraints);
    }
  }
  ((void (*)(id,SEL,CGRect))compatFrame)(self,command,frame);
}
static CGSize InputSize(id self, SEL command, id controller, UIView *view, BOOL assistant) {
  CGSize result = ((CGSize (*)(id,SEL,id,UIView *,BOOL))inputSize)(self,command,controller,view,assistant);
  // Causal control in the synthetic host only. This is not a keyboard fix and
  // must never be shipped: Clarify does not control third-party host apps.
  if ([NSStringFromClass(view.class) isEqualToString:@"_UIKBCompatInputView"] &&
      view.intrinsicContentSize.height == UIViewNoIntrinsicMetric) {
    NSLog(@"ClarifyHostFallback %@ -> 216", NSStringFromCGSize(result));
    result.height = 216;
  }
  if (eventCount < 350) {
    eventCount++;
    NSLog(@"ClarifyHostFrame size-for controller=%@ view=%@ assistant=%d result=%@ padding=%@", NSStringFromClass([controller class]), ViewGeometry(view), assistant, NSStringFromCGSize(result), Read(self,@"_inputViewPadding"));
  }
  return result;
}
static void Install(NSString *name, NSString *selector, IMP replacement, IMP *original) {
  Class cls = NSClassFromString(name); SEL sel = NSSelectorFromString(selector);
  Method method = cls ? class_getInstanceMethod(cls,sel) : NULL;
  NSLog(@"ClarifyHostGeometry install %@ %@ available=%d", name, selector, method != NULL);
  if (!method) return;
  *original = method_getImplementation(method);
  if (!class_addMethod(cls,sel,replacement,method_getTypeEncoding(method))) method_setImplementation(method,replacement);
}
void ClarifyInstallHostGeometry(void) {
  static dispatch_once_t once;
  dispatch_once(&once, ^{
  previous = [NSMutableDictionary new];
  Install(@"UIInputWindowControllerHosting", @"updateViewSizingConstraints", (IMP)HostingSizing, &hostingSizing);
  Install(@"UIInputWindowControllerHostingItem", @"updateViewSizingConstraints", (IMP)ItemSizing, &itemSizing);
  Install(@"UIInputLayoutHostingItem", @"updateViewSizingConstraints", (IMP)LayoutSizing, &layoutSizing);
  Install(@"_UIRemoteInputViewController", @"intrinsicContentSizeForServiceSize:", (IMP)RemoteIntrinsic, &remoteIntrinsic);
  Install(@"UIInputWindowController", @"updateKeyboardLayoutGuideWithFrame:layoutViews:", (IMP)GuideFrame, &guideFrame);
  Install(@"_UIKBCompatInputView", @"setFrame:", (IMP)CompatFrame, &compatFrame);
  Install(@"UIInputWindowController", @"sizeForInputViewController:inputView:includeAssistantBar:", (IMP)InputSize, &inputSize);
  });
}
