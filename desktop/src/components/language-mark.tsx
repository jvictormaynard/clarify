import { useId } from 'react';
import { Globe } from 'lucide-react';

/** Small flat flag illustrations share one proportion and rounded frame. */
export function LanguageMark({code}: {code?: string}) {
  const clip = useId();
  if (!['en', 'pt', 'es', 'de', 'ru'].includes(code || '')) return <span className="language-mark language-mark-original" aria-hidden="true"><Globe /></span>;
  return <svg className="language-mark" data-language={code} viewBox="0 0 24 18" fill="none" aria-hidden="true">
    <defs><clipPath id={clip}><rect width="24" height="18" rx="3.5" /></clipPath></defs>
    <g clipPath={`url(#${clip})`}>
      {code === 'en' && <>
        <path fill="#FFFFFF" d="M0 0h24v18H0z" />
        {Array.from({length:7}, (_, index) => <rect key={index} y={index * 36 / 13} width="24" height={18 / 13} fill="#E3293F" />)}
        <path fill="#204B9B" d="M0 0h11v9.7H0z" />
        {[2,4.8,7.6].flatMap(y => [2,5.5,9].map(x => <circle key={`${x}-${y}`} cx={x} cy={y} r=".65" fill="#FFFFFF" />))}
      </>}
      {code === 'pt' && <>
        <path fill="#009C3B" d="M0 0h24v18H0z" />
        <path fill="#FFDF00" d="m12 2 9 7-9 7-9-7z" />
        <circle cx="12" cy="9" r="4.3" fill="#002776" />
        <path d="M8 7.5c3-.3 5.5.5 7.6 2.7" stroke="#FFFFFF" strokeWidth=".9" />
      </>}
      {code === 'es' && <>
        <path fill="#D91B32" d="M0 0h24v18H0z" />
        <path fill="#FFD12A" d="M0 4.5h24v9H0z" />
        <path fill="#D91B32" d="M6.5 7h3v3a1.5 1.5 0 0 1-3 0z" />
        <path stroke="#F5E3A6" strokeWidth=".7" d="M8 7.5v3M6.5 9h3" />
      </>}
      {code === 'de' && <>
        <path fill="#101010" d="M0 0h24v6H0z" /><path fill="#DF1434" d="M0 6h24v6H0z" /><path fill="#FFCE00" d="M0 12h24v6H0z" />
      </>}
      {code === 'ru' && <>
        <path fill="#FFFFFF" d="M0 0h24v6H0z" /><path fill="#165CC9" d="M0 6h24v6H0z" /><path fill="#E3223B" d="M0 12h24v6H0z" />
      </>}
    </g>
    <rect x=".5" y=".5" width="23" height="17" rx="3" stroke="#fff" strokeOpacity=".14" />
  </svg>;
}
