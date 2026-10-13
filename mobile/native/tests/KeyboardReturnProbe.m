#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <objc/message.h>

NSDictionary *ClarifyReturnDiagnostics(void) {
  NSMutableDictionary *result = [NSMutableDictionary dictionary];
  @try {
    id app = UIApplication.sharedApplication;
    Ivar ivar = class_getInstanceVariable(UIApplication.class, "_systemNavigationAction");
    id action = ivar ? object_getIvar(app, ivar) : nil;
    result[@"navigationAction"] = action ? NSStringFromClass([action class]) : @"nil";
    SEL send = NSSelectorFromString(@"sendResponseForDestination:");
    NSMethodSignature *signature = [action methodSignatureForSelector:send];
    result[@"navigationReturnType"] = signature ? @(signature.methodReturnType) : @"missing";
    result[@"navigationArgument"] = signature ? @([signature getArgumentTypeAtIndex:2]) : @"missing";
    Class cls = NSClassFromString(@"LSApplicationWorkspace");
    SEL getter = NSSelectorFromString(@"defaultWorkspace");
    id workspace = [cls respondsToSelector:getter] ? ((id (*)(id, SEL))objc_msgSend)(cls, getter) : nil;
    signature = [workspace methodSignatureForSelector:NSSelectorFromString(@"openApplicationWithBundleID:")];
    result[@"workspaceReturnType"] = signature ? @(signature.methodReturnType) : @"missing";
  } @catch (__unused NSException *exception) { result[@"exception"] = @YES; }
  return result;
}
