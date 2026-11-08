#pragma once
#import <UIKit/UIKit.h>

NS_ASSUME_NONNULL_BEGIN

FOUNDATION_EXPORT void ClarifyKeyboardHeightDidLayout(UIInputViewController *child);
FOUNDATION_EXPORT void ClarifyKeyboardHeightDidAppear(UIInputViewController *child);
FOUNDATION_EXPORT void ClarifyKeyboardHeightDidDisappear(UIInputViewController *child);

NS_ASSUME_NONNULL_END
