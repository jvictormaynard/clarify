// Isolated diagnostic only. No private geometry code belongs in the product.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <objc/message.h>
#import <string.h>
#import "GeometryConfig.h"

static IMP hostWillAppear;
NSString *ClarifyGeometryVariant(void) {
  return [NSString stringWithContentsOfFile:CLARIFY_GEOMETRY_CONFIG encoding:NSUTF8StringEncoding error:nil] ?: @"baseline";
}
void ClarifyGeometryPrepareParent(UIViewController *parent) {}
void ClarifyGeometryConfigure(UIInputViewController *controller) {}
void ClarifyGeometryFinish(void) {}
void ClarifyGeometryLogController(UIInputViewController *controller, NSString *phase) {}

static void PublishSize(id parent, id fence) {
  Ivar ivar = parent ? class_getInstanceVariable(object_getClass(parent), "_remoteViewControllerProxyToOperator") : NULL;
  id proxy = ivar ? object_getIvar(parent, ivar) : nil;
  SEL selector = NSSelectorFromString(@"__viewServiceInstrinsicContentSizeDidChange:fence:");
  NSMethodSignature *signature = [proxy methodSignatureForSelector:selector];
  if (signature.numberOfArguments != 4 || strcmp(signature.methodReturnType, "v") ||
      strncmp([signature getArgumentTypeAtIndex:2], "{CGSize=", 8) || [signature getArgumentTypeAtIndex:3][0] != '@') return;
  CGSize size = CGSizeMake(UIScreen.mainScreen.bounds.size.width, 216);
  ((void (*)(id, SEL, CGSize, id))objc_msgSend)(proxy, selector, size, fence);
  NSLog(@"ClarifyAppearanceSize published %@ fence=%@", ClarifyGeometryVariant(), NSStringFromClass([fence class]));
}

// Clang Block ABI: only wrap a verified void block with one CGSize parameter.
// An unfamiliar signature is forwarded unchanged, never called with guessed args.
static BOOL IsSizeReply(id block) {
  if (!block) return NO;
  struct BlockLayout { void *isa; int flags; int reserved; void *invoke; void *descriptor; };
  const struct BlockLayout *layout = (__bridge const void *)block;
  if (!(layout->flags & (1 << 30))) return NO;
  const uint8_t *descriptor = layout->descriptor;
  descriptor += 2 * sizeof(uintptr_t);
  if (layout->flags & (1 << 25)) descriptor += 2 * sizeof(void *);
  const char *types = *(const char * const *)descriptor;
  NSMethodSignature *signature = [NSMethodSignature signatureWithObjCTypes:types];
  NSLog(@"ClarifyAppearanceSize reply-signature %s", types);
  return !strcmp(signature.methodReturnType, "v") && signature.numberOfArguments == 2 &&
    !strncmp([signature getArgumentTypeAtIndex:1], "{CGSize=", 8);
}
static void HostWillAppear(id self, SEL command, BOOL animated, long long orientation,
                           id traits, double statusHeight, BOOL underlaps, id completion) {
  NSString *variant = ClarifyGeometryVariant();
  NSLog(@"ClarifyAppearanceSize will-appear %@", variant);
  if ([variant isEqualToString:@"appear-before"]) PublishSize(self, nil);
  id forwarded = completion;
  if ([variant hasPrefix:@"reply-"] && IsSizeReply(completion)) {
    void (^reply)(CGSize) = completion;
    forwarded = ^(CGSize originalSize) {
      CGSize size = CGSizeMake(UIScreen.mainScreen.bounds.size.width, 216);
      NSLog(@"ClarifyAppearanceSize reply %@ %@ -> %@", variant, NSStringFromCGSize(originalSize), NSStringFromCGSize(size));
      if ([variant isEqualToString:@"reply-notify"]) PublishSize(self, nil);
      if ([variant isEqualToString:@"reply-size-async"]) {
        dispatch_async(dispatch_get_main_queue(), ^{ reply(size); });
      } else { reply(size); }
    };
  }
  ((void (*)(id, SEL, BOOL, long long, id, double, BOOL, id))hostWillAppear)(self, command, animated, orientation, traits, statusHeight, underlaps, forwarded);
  if ([variant isEqualToString:@"appear-after"]) PublishSize(self, nil);
}

@interface ClarifyAppearanceSizeProbe : NSObject @end
@implementation ClarifyAppearanceSizeProbe
+ (void)load {
  Class cls = NSClassFromString(@"_UIViewServiceViewControllerOperator");
  SEL selector = NSSelectorFromString(@"__hostViewWillAppear:inInterfaceOrientation:traitCollection:statusBarHeight:underlapsStatusBar:completionHandler:");
  Method method = class_getInstanceMethod(cls, selector);
  if (!method) { NSLog(@"ClarifyAppearanceSize missing method"); return; }
  NSLog(@"ClarifyAppearanceSize installed %s", method_getTypeEncoding(method));
  hostWillAppear = method_getImplementation(method);
  if (!class_addMethod(cls, selector, (IMP)HostWillAppear, method_getTypeEncoding(method))) method_setImplementation(method, (IMP)HostWillAppear);
}
@end
