#import <Foundation/Foundation.h>
#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN

// All entry points require the main thread. Completion is always on main.
@interface ClarifyPrivateWritingToolsBridge : NSObject
+ (NSDictionary<NSString *, id> *)probe;
+ (BOOL)isBusy;
+ (void)rewrite:(NSString *)source
          style:(NSString *)style
    operationID:(NSString *)operationID
     completion:(void (^)(NSDictionary<NSString *, id> *reply))completion;
+ (void)cancelOperation:(NSString *)operationID;
// YES means start was invoked, not that presentation or rewriting succeeded.
+ (BOOL)openToolForTextView:(UITextView *)textView
                     style:(NSString *)style
               diagnostics:(NSString * _Nullable __autoreleasing * _Nullable)diagnostics;
@end

NS_ASSUME_NONNULL_END
