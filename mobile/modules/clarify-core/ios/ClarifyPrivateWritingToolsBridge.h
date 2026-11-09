#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN

// All entry points require the main thread. Completion is always on main.
@interface ClarifyPrivateWritingToolsBridge : NSObject
+ (NSDictionary<NSString *, id> *)probe NS_SWIFT_NAME(probe());
+ (BOOL)isBusy NS_SWIFT_NAME(isBusy());
+ (void)rewrite:(NSString *)source
          style:(NSString *)style
    operationID:(NSString *)operationID
     completion:(void (^)(NSDictionary<NSString *, id> *reply))completion NS_SWIFT_NAME(rewrite(_:style:operationID:completion:));
+ (void)cancelOperation:(NSString *)operationID NS_SWIFT_NAME(cancelOperation(_:));
// YES means start was invoked, not that presentation or rewriting succeeded.
+ (BOOL)openToolForTextView:(UITextView *)textView
                     style:(NSString *)style
               diagnostics:(NSString * _Nullable __autoreleasing * _Nullable)diagnostics NS_SWIFT_NAME(openTool(textView:style:diagnostics:));
+ (void)endToolForTextView:(UITextView *)textView NS_SWIFT_NAME(endTool(textView:));
@end

NS_ASSUME_NONNULL_END
