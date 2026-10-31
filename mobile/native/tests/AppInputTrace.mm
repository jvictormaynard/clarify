// Temporary simulator-fixture diagnostics. Never added to the shipping project.
#import <UIKit/UIKit.h>
#import <objc/runtime.h>
#import <os/log.h>

static IMP originalInsert, originalText, originalAttributed, originalReplace, originalEnabled;

static void Record(UITextField *field, NSString *event, NSString *incoming)
{
  // UIKit calls setters during initialization. Observe attached fields only.
  if (!field.window) return;
  NSDictionary *value = @{
    @"time": @([NSDate date].timeIntervalSince1970),
    @"event": event,
    @"field": [NSString stringWithFormat:@"%p", field],
    @"label": field.accessibilityLabel ?: @"",
    @"text": field.text ?: @"",
    @"incoming": incoming ?: @"",
    @"enabled": @(field.enabled),
    @"focused": @(field.isFirstResponder)
  };
  NSData *data = [NSJSONSerialization dataWithJSONObject:value options:0 error:nullptr];
  NSString *json = [[NSString alloc] initWithData:data encoding:NSUTF8StringEncoding];
  os_log(OS_LOG_DEFAULT, "CLARIFY_INPUT_NATIVE %{public}@", json);
}

static void Insert(id field, SEL selector, NSString *text)
{
  Record(field, @"insert.before", text);
  ((void (*)(id, SEL, NSString *))originalInsert)(field, selector, text);
  Record(field, @"insert.after", text);
}

static void Text(id field, SEL selector, NSString *text)
{
  Record(field, @"text.before", text);
  ((void (*)(id, SEL, NSString *))originalText)(field, selector, text);
  Record(field, @"text.after", text);
}

static void Attributed(id field, SEL selector, NSAttributedString *text)
{
  Record(field, @"attributed.before", text.string);
  ((void (*)(id, SEL, NSAttributedString *))originalAttributed)(field, selector, text);
  Record(field, @"attributed.after", text.string);
}

static void Replace(id field, SEL selector, UITextRange *range, NSString *text)
{
  Record(field, @"replace.before", text);
  ((void (*)(id, SEL, UITextRange *, NSString *))originalReplace)(field, selector, range, text);
  Record(field, @"replace.after", text);
}

static void Enabled(id field, SEL selector, BOOL enabled)
{
  Record(field, @"enabled.before", enabled ? @"true" : @"false");
  ((void (*)(id, SEL, BOOL))originalEnabled)(field, selector, enabled);
  Record(field, @"enabled.after", enabled ? @"true" : @"false");
}

static void Hook(Class type, SEL selector, IMP replacement, IMP *original)
{
  Method method = class_getInstanceMethod(type, selector);
  if (!method) {
    os_log(OS_LOG_DEFAULT, "CLARIFY_INPUT_NATIVE missing selector %{public}@", NSStringFromSelector(selector));
    return;
  }
  *original = method_getImplementation(method);
  // Add an override when the implementation is inherited. Never replace UIKit's
  // base implementation, which would affect other classes in the process.
  if (!class_addMethod(type, selector, replacement, method_getTypeEncoding(method))) {
    method_setImplementation(class_getInstanceMethod(type, selector), replacement);
  }
}

@interface ClarifyAppInputTrace : NSObject
@end

@implementation ClarifyAppInputTrace
+ (void)load
{
  Class type = NSClassFromString(@"RCTUITextField");
  if (!type) {
    os_log(OS_LOG_DEFAULT, "CLARIFY_INPUT_NATIVE RCTUITextField unavailable");
    return;
  }
  Hook(type, @selector(insertText:), (IMP)Insert, &originalInsert);
  Hook(type, @selector(setText:), (IMP)Text, &originalText);
  Hook(type, @selector(setAttributedText:), (IMP)Attributed, &originalAttributed);
  Hook(type, @selector(replaceRange:withText:), (IMP)Replace, &originalReplace);
  Hook(type, @selector(setEnabled:), (IMP)Enabled, &originalEnabled);
  [[NSNotificationCenter defaultCenter] addObserverForName:UITextFieldTextDidChangeNotification
    object:nil queue:nil usingBlock:^(NSNotification *notification) {
      if ([notification.object isKindOfClass:type]) Record(notification.object, @"change.notification", nil);
    }];
  for (NSString *name in @[UIKeyboardDidShowNotification, UIKeyboardDidHideNotification, UIKeyboardDidChangeFrameNotification]) {
    [[NSNotificationCenter defaultCenter] addObserverForName:name object:nil queue:nil usingBlock:^(NSNotification *notification) {
      os_log(OS_LOG_DEFAULT, "CLARIFY_INPUT_NATIVE keyboard %{public}@ %{public}@", notification.name,
        notification.userInfo[UIKeyboardFrameEndUserInfoKey]);
    }];
  }
  os_log(OS_LOG_DEFAULT, "CLARIFY_INPUT_NATIVE installed");
}
@end
