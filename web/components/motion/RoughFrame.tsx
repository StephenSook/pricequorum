/**
 * Torn, brush-edged frame around the viewport. A turbulence displacement roughens a thick
 * border so the page reads like a painted board, echoing the reference site's vignette.
 */
export function RoughFrame() {
  return (
    <div aria-hidden="true" className="pointer-events-none fixed inset-0 z-[var(--z-framing)] overflow-hidden">
      <svg className="absolute h-0 w-0">
        <filter id="pq-rough-edge" x="-10%" y="-10%" width="120%" height="120%">
          <feTurbulence type="fractalNoise" baseFrequency="0.035" numOctaves="4" seed="7" />
          <feDisplacementMap in="SourceGraphic" scale="28" xChannelSelector="R" yChannelSelector="G" />
        </filter>
      </svg>
      <div className="absolute -inset-5 border-[38px] border-[#3b2a1c]" style={{ filter: "url(#pq-rough-edge)" }} />
    </div>
  );
}
