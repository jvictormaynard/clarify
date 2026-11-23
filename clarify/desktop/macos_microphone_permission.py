"""Check and request microphone access through AVFoundation on macOS."""

from functools import cache


@cache
def _av_capture():
    import objc

    symbols = {}
    framework = objc.loadBundle(
        "ClarifyAVFoundation",
        symbols,
        bundle_path="/System/Library/Frameworks/AVFoundation.framework",
    )
    objc.loadBundleVariables(framework, symbols, [("AVMediaTypeAudio", b"@")])
    # PyObjC needs the completion block signature when loading AVFoundation
    # directly through the existing Cocoa runtime.
    objc.registerMetaDataForSelector(
        b"AVCaptureDevice",
        b"requestAccessForMediaType:completionHandler:",
        {
            "arguments": {
                3: {
                    "callable": {
                        "retval": {"type": b"v"},
                        "arguments": {0: {"type": b"^v"}, 1: {"type": b"Z"}},
                    }
                }
            }
        },
    )
    return objc.lookUpClass("AVCaptureDevice"), symbols["AVMediaTypeAudio"]


def microphone_permission_status() -> str:
    device, media_type = _av_capture()
    # AVAuthorizationStatus: not determined, restricted, denied, authorized.
    status = device.authorizationStatusForMediaType_(media_type)
    return {0: "request", 3: "allowed"}.get(status, "settings")


def request_microphone_permission(completed) -> None:
    device, media_type = _av_capture()
    device.requestAccessForMediaType_completionHandler_(media_type, completed)
