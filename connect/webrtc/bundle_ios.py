"""Bundle the app-owned RTC modules for WKWebView without remote scripts."""

import argparse
from pathlib import Path

WRAPPER = """
let nativePeer;
window.clarifyRTC = Object.freeze({
 async connect(host, key) {
   if (nativePeer) throw Error('already_connected');
   let retired = false;
   const signal = (action, fields = {}) => window.webkit.messageHandlers.signal.postMessage({action, ...fields});
   const onClose = () => {
     if (retired) return;
     retired = true; nativePeer = null;
     void window.webkit.messageHandlers.signal.postMessage({event:'closed'}).catch(() => {});
   };
   const peer = await connectComputer({signal, host, pinnedPublicKey:key, onClose});
   if (retired) { peer.pc.close(); throw Error('response_uncertain'); }
   nativePeer = peer;
 },
 send: (value, timeout) => { if (!nativePeer) throw Error('offline'); return nativePeer.rpc.request(value, {timeout}); },
 close: () => { nativePeer?.rpc.close(); nativePeer?.pc.close(); nativePeer = null; }
});
"""


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[2]
    modules = root / "desktop/electron"
    script = (modules / "webrtc-transport.mjs").read_text().replace("export ", "")
    script += "\n" + (modules / "webrtc-signaling.mjs").read_text().replace(
        "import {clientOffer, hostAnswer} from './webrtc-transport.mjs';", ""
    ).replace("export ", "")
    script += WRAPPER
    target = root / "mobile/modules/clarify-core/ios/ComputerWebRTC/computer-webrtc.js"
    if args.check:
        if target.read_text() != script:
            raise SystemExit(
                "Rebuild the iOS RTC bundle with python -m connect.webrtc.bundle_ios"
            )
    else:
        target.write_text(script)


if __name__ == "__main__":
    main()
