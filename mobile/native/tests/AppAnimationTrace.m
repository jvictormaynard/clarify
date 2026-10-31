// Diagnostic only. Linked into the copied localhost fixture, never the product.
#import <UIKit/UIKit.h>
#import <QuartzCore/QuartzCore.h>
#import <CoreFoundation/CoreFoundation.h>
#import <math.h>

static NSString *TracePath;
static NSUInteger Sequence;

static id Number(double value) { return isfinite(value) ? @(value) : @"nonfinite"; }
static NSString *Bound(NSString *value) { return [value substringToIndex:MIN(128, value.length)]; }

static void Layers(CALayer *layer, NSMutableArray *out, NSUInteger *visited) {
  if (++*visited > 2000 || out.count >= 128) return;
  for (NSString *key in layer.animationKeys) {
    CAAnimation *animation = [layer animationForKey:key];
    if (!animation) continue;
    NSMutableDictionary *entry = [@{@"layer": NSStringFromClass(layer.class),
      @"owner": layer.delegate ? NSStringFromClass([layer.delegate class]) : @"",
      @"key": Bound(key), @"kind": NSStringFromClass(animation.class),
      @"duration": Number(animation.duration), @"repeatCount": Number(animation.repeatCount),
      @"repeatDuration": Number(animation.repeatDuration), @"speed": Number(animation.speed),
      @"removedOnCompletion": @(animation.removedOnCompletion), @"hidden": @(layer.hidden),
      @"opacity": Number(layer.opacity), @"frame": NSStringFromCGRect(layer.frame)} mutableCopy];
    if ([animation isKindOfClass:CAPropertyAnimation.class]) entry[@"keyPath"] = Bound([(CAPropertyAnimation *)animation keyPath] ?: @"");
    [out addObject:entry];
    if (out.count >= 128) break;
  }
  for (CALayer *child in layer.sublayers) Layers(child, out, visited);
}

static void Views(UIView *view, NSMutableArray *out, NSUInteger *visited, BOOL ancestorHidden) {
  if (++*visited > 2000 || out.count >= 128) return;
  BOOL hidden = ancestorHidden || view.hidden || view.alpha <= 0;
  BOOL input = [view isKindOfClass:UITextField.class] || [view isKindOfClass:UITextView.class];
  if (view.isFirstResponder || [view isKindOfClass:UIActivityIndicatorView.class] || [view isKindOfClass:UIScrollView.class]) {
    NSMutableDictionary *entry = [@{@"kind": NSStringFromClass(view.class),
      @"identifier": Bound(view.accessibilityIdentifier ?: @""), @"hidden": @(hidden),
      @"frame": NSStringFromCGRect([view convertRect:view.bounds toView:view.window]),
      @"firstResponder": @(view.isFirstResponder)} mutableCopy];
    if ([view isKindOfClass:UIActivityIndicatorView.class]) entry[@"animating"] = @([(UIActivityIndicatorView *)view isAnimating]);
    if ([view isKindOfClass:UIScrollView.class]) {
      UIScrollView *scroll = (UIScrollView *)view;
      entry[@"dragging"] = @(scroll.dragging); entry[@"decelerating"] = @(scroll.decelerating);
      entry[@"offset"] = NSStringFromCGPoint(scroll.contentOffset);
    }
    if (input) {
      UIView<UITextInput> *field = (UIView<UITextInput> *)view;
      UITextRange *range = field.selectedTextRange;
      entry[@"textLength"] = @([[(id)view text] length]);
      entry[@"selectionLength"] = range ? @([field offsetFromPosition:range.start toPosition:range.end]) : @0;
      entry[@"marked"] = @(field.markedTextRange != nil);
    }
    [out addObject:entry];
  }
  for (UIView *child in view.subviews) Views(child, out, visited, hidden);
}

static void Write(NSString *event) {
  NSMutableArray *layers = [NSMutableArray array], *views = [NSMutableArray array], *controllers = [NSMutableArray array];
  NSUInteger layerCount = 0, viewCount = 0;
  for (UIScene *scene in UIApplication.sharedApplication.connectedScenes) {
    if (![scene isKindOfClass:UIWindowScene.class]) continue;
    for (UIWindow *window in [(UIWindowScene *)scene windows]) {
      Layers(window.layer, layers, &layerCount); Views(window, views, &viewCount, NO);
      UIViewController *controller = window.rootViewController;
      for (NSUInteger depth = 0; controller && depth < 16; depth++, controller = controller.presentedViewController) {
        [controllers addObject:@{@"kind": NSStringFromClass(controller.class),
          @"transitioning": @(controller.transitionCoordinator != nil),
          @"presenting": @(controller.isBeingPresented), @"dismissing": @(controller.isBeingDismissed)}];
      }
    }
  }
  NSDictionary *record = @{@"event": event, @"sequence": @(++Sequence),
    @"pid": @(NSProcessInfo.processInfo.processIdentifier), @"uptime": @(NSProcessInfo.processInfo.systemUptime),
    @"mainThread": @(NSThread.isMainThread), @"reduceMotion": @(UIAccessibilityIsReduceMotionEnabled()),
    @"layersVisited": @(layerCount), @"viewsVisited": @(viewCount),
    @"animations": layers, @"views": views, @"controllers": controllers};
  NSData *data = [NSJSONSerialization dataWithJSONObject:record options:0 error:nil];
  if (!data) return;
  NSFileHandle *file = [NSFileHandle fileHandleForWritingAtPath:TracePath];
  [file seekToEndOfFile]; [file writeData:data]; [file writeData:[@"\n" dataUsingEncoding:NSUTF8StringEncoding]]; [file closeFile];
}

static void Capture(CFNotificationCenterRef center, void *observer, CFStringRef name, const void *object, CFDictionaryRef info) {
  dispatch_async(dispatch_get_main_queue(), ^{ Write(@"capture"); });
}

__attribute__((constructor)) static void PrepareAnimationTrace(void) {
  [NSNotificationCenter.defaultCenter addObserverForName:UIApplicationDidFinishLaunchingNotification object:nil queue:NSOperationQueue.mainQueue usingBlock:^(__unused NSNotification *note) {
    NSURL *url = [NSURL URLWithString:[NSBundle.mainBundle objectForInfoDictionaryKey:@"ClarifyCloudURL"] ?: @""];
    if (![url.scheme isEqualToString:@"http"] || ![@[@"127.0.0.1", @"localhost"] containsObject:url.host]) return;
    TracePath = [NSSearchPathForDirectoriesInDomains(NSCachesDirectory, NSUserDomainMask, YES).firstObject stringByAppendingPathComponent:@"clarify-animation-trace.jsonl"];
    if (![NSFileManager.defaultManager fileExistsAtPath:TracePath]) [NSFileManager.defaultManager createFileAtPath:TracePath contents:nil attributes:nil];
    Write(@"installed");
    CFNotificationCenterAddObserver(CFNotificationCenterGetDarwinNotifyCenter(), NULL, Capture,
      CFSTR("com.clarify.fixture.animation-capture"), NULL, CFNotificationSuspensionBehaviorDeliverImmediately);
  }];
}
