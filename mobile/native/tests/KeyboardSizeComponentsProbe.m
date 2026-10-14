// Diagnostic host only. Observe sizing components without changing return values.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <stdatomic.h>

static CGSize (*originalTotal)(id, SEL, NSInteger, BOOL, BOOL);
static CGSize (*originalBase)(id, SEL, NSInteger, BOOL);
static UIEdgeInsets (*originalPadding)(id, SEL, NSInteger, id);
static UIEdgeInsets (*originalBuffer)(id, SEL, NSInteger, id);
static CGFloat (*originalAssistant)(id, SEL, UITraitCollection *, NSInteger);
static _Atomic unsigned requests;
static _Thread_local unsigned requestID;

static CGSize totalSize(id object, SEL command, NSInteger orientation, BOOL assistant, BOOL ignore) {
    unsigned previous = requestID;
    requestID = atomic_fetch_add(&requests, 1) + 1;
    if (requestID <= 1000) NSLog(@"ClarifySizeComponent request=%u begin orientation=%ld assistant=%d ignore=%d", requestID, (long)orientation, assistant, ignore);
    CGSize result = originalTotal(object, command, orientation, assistant, ignore);
    if (requestID <= 1000) NSLog(@"ClarifySizeComponent request=%u total=%@", requestID, NSStringFromCGSize(result));
    requestID = previous;
    return result;
}

static CGSize baseSize(id object, SEL command, NSInteger orientation, BOOL ignore) {
    CGSize result = originalBase(object, command, orientation, ignore);
    if (requestID && requestID <= 1000) NSLog(@"ClarifySizeComponent request=%u base=%@", requestID, NSStringFromCGSize(result));
    return result;
}

static UIEdgeInsets paddingSize(id object, SEL command, NSInteger orientation, id mode) {
    UIEdgeInsets result = originalPadding(object, command, orientation, mode);
    if (requestID && requestID <= 1000) NSLog(@"ClarifySizeComponent request=%u padding=%@ mode=%@", requestID, NSStringFromUIEdgeInsets(result), NSStringFromClass([mode class]));
    return result;
}

static UIEdgeInsets bufferSize(id object, SEL command, NSInteger orientation, id mode) {
    UIEdgeInsets result = originalBuffer(object, command, orientation, mode);
    if (requestID && requestID <= 1000) NSLog(@"ClarifySizeComponent request=%u buffer=%@", requestID, NSStringFromUIEdgeInsets(result));
    return result;
}

static CGFloat assistantSize(id object, SEL command, UITraitCollection *traits, NSInteger orientation) {
    CGFloat result = originalAssistant(object, command, traits, orientation);
    if (requestID && requestID <= 1000) NSLog(@"ClarifySizeComponent request=%u assistantHeight=%g idiom=%ld horizontal=%ld vertical=%ld", requestID, result, (long)traits.userInterfaceIdiom, (long)traits.horizontalSizeClass, (long)traits.verticalSizeClass);
    return result;
}

static IMP observe(Class type, BOOL classMethod, NSString *name, IMP replacement) {
    SEL selector = NSSelectorFromString(name);
    Method method = classMethod ? class_getClassMethod(type, selector) : class_getInstanceMethod(type, selector);
    NSLog(@"ClarifySizeComponent install %@ %@ signature=%s", NSStringFromClass(type), name, method ? method_getTypeEncoding(method) : "missing");
    if (!method) return NULL;
    return method_setImplementation(method, replacement);
}

@interface KeyboardSizeComponentsProbe : NSObject
@end
@implementation KeyboardSizeComponentsProbe
+ (void)load {
    Class keyboard = NSClassFromString(@"UIKeyboard");
    Class impl = NSClassFromString(@"UIKeyboardImpl");
    originalTotal = (void *)observe(keyboard, YES, @"sizeForInterfaceOrientation:includingAssistantBar:ignoreInputView:", (IMP)totalSize);
    originalBase = (void *)observe(impl, YES, @"sizeForInterfaceOrientation:ignoreInputView:", (IMP)baseSize);
    originalPadding = (void *)observe(impl, YES, @"deviceSpecificPaddingForInterfaceOrientation:inputMode:", (IMP)paddingSize);
    originalBuffer = (void *)observe(impl, YES, @"deviceSpecificStaticHitBufferForInterfaceOrientation:inputMode:", (IMP)bufferSize);
    originalAssistant = (void *)observe(NSClassFromString(@"UISystemInputAssistantViewController"), NO, @"preferredHeightForTraitCollection:orientation:", (IMP)assistantSize);
}
@end
