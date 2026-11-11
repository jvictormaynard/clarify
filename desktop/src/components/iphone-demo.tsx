import { ArrowUp, Check, ChevronDown, ChevronLeft, Delete, Globe, Mic, Plus, ArrowBigUp, Video, X } from "lucide-react";
import { t, uiLanguage } from "../i18n";
import { LanguageMark } from "./language-mark";
import { writingStyleNames } from "../settings/writing-style-options";
import landscape from "../assets/iphone-demo-landscape.webp";

// A full-resolution iPhone canvas, scaled only at its outer camera layer.
// Recording replaces the keys, as it does in the native Clarify extension.
export function IPhoneDemo() {
  return <div className="iphone-demo" aria-hidden="true">
    <img className="iphone-demo-landscape" src={landscape} alt="" />
    <div className="iphone-demo-light" />
    <div className="iphone-demo-camera">
      <div className="iphone-demo-device">
        <i className="iphone-demo-action-button" /><i className="iphone-demo-volume up" /><i className="iphone-demo-volume down" /><i className="iphone-demo-power" />
        <div className="iphone-demo-bezel" />
        <div className="iphone-demo-screen">
          <div className="iphone-demo-statusbar"><b>9:41</b><div className="iphone-demo-status-icons">
            <svg width="19" height="15" viewBox="0 0 19 15" fill="currentColor"><rect x="0" y="10" width="3" height="5" rx=".7" /><rect x="5" y="7" width="3" height="8" rx=".7" /><rect x="10" y="3" width="3" height="12" rx=".7" /><rect x="15" width="3" height="15" rx=".7" /></svg>
            <svg width="19" height="15" viewBox="0 0 20 16" fill="none" stroke="currentColor" strokeWidth="2.5" strokeLinecap="round"><path d="M2 4a13 13 0 0 1 16 0M5 8a8 8 0 0 1 10 0M8 12a3 3 0 0 1 4 0" /><circle cx="10" cy="15" r="1" fill="currentColor" stroke="none" /></svg>
            <span className="iphone-demo-battery"><i /></span>
          </div></div>
          <div className="iphone-demo-island"><i /></div>
          <div className="iphone-demo-chat-header"><ChevronLeft size={28} /><div><span className="iphone-demo-avatar">A</span><span>Alex <ChevronDown size={10} /></span></div><Video size={25} /></div>
          <div className="iphone-demo-chat-date">{t("Hoje")} 9:41</div>
          <div className="iphone-demo-incoming">{t("Quando podemos conversar?")}</div>
          <div className="iphone-demo-composer">
            <Plus size={29} />
            <div className="iphone-demo-input"><span className="iphone-demo-placeholder">{t("Mensagem")}</span><span className="iphone-demo-result">{t("Olá! Podemos conversar amanhã?")}</span><span className="iphone-demo-caret" /><span className="iphone-demo-send"><ArrowUp size={22} /></span></div>
          </div>
          <div className="iphone-demo-keyboard">
            <span className="iphone-demo-language"><LanguageMark code={uiLanguage} />{t(writingStyleNames.natural)}</span>
            <div className="iphone-demo-typing">
              <div className="iphone-demo-toolbar"><span className="iphone-demo-microphone"><Mic size={24} /></span></div>
              <div className="iphone-demo-keys">
                {["QWERTYUIOP", "ASDFGHJKL", "ZXCVBNM"].map((row, index) => <div className={`iphone-demo-key-row row-${index}`} key={row}>
                  {index === 2 && <span className="iphone-demo-key special shift"><ArrowBigUp size={24} fill="currentColor" /></span>}
                  {[...row].map(key => <span className="iphone-demo-key" key={key}>{key}</span>)}
                  {index === 2 && <span className="iphone-demo-key special delete"><Delete size={25} /></span>}
                </div>)}
                <div className="iphone-demo-key-row bottom"><span className="iphone-demo-key special">123</span><span className="iphone-demo-key special globe"><Globe size={23} /></span><span className="iphone-demo-key space">{t("espaço")}</span><span className="iphone-demo-key special return">{t("retorno")}</span></div>
              </div>
            </div>
            <div className="iphone-demo-recording"><span className="iphone-demo-cancel"><X size={24} /></span><span className="iphone-demo-finish"><Check size={23} /><i className="iphone-demo-spinner" /></span>
              <div className="iphone-demo-waveform">{[20, 34, 46, 30, 50, 38, 56, 40, 26, 44, 32, 18].map((height, index) => <i key={index} style={{ height, animationDelay: `${index * -.09}s` }} />)}</div>
              <span className="iphone-demo-listening">{t("Ouvindo…")}</span><span className="iphone-demo-transcribing">{t("Transcrevendo…")}</span><Globe className="iphone-demo-recording-globe" size={24} />
            </div>
          </div>
          <i className="iphone-demo-touch start" /><i className="iphone-demo-touch finish" />
          <div className="iphone-demo-home-indicator" />
        </div>
      </div>
    </div>
  </div>;
}
