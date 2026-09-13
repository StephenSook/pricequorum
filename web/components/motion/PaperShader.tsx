"use client";

import { useEffect, useRef, useState } from "react";

import { prefersReducedMotion } from "@/lib/motion/prefersReducedMotion";

// Earliest start: the preloader's 2 s minimum plus its 0.62 s exit. After that the shader still waits
// until the preloader has left the DOM. The WebGL code loads only then.
const START_DELAY_MS = 2800;
const MAX_DPR = 1.5;

const VERTEX = /* glsl */ `
attribute vec2 uv;
attribute vec2 position;
varying vec2 vUv;
void main() {
  vUv = uv;
  gl_Position = vec4(position, 0.0, 1.0);
}
`;

const FRAGMENT = /* glsl */ `
precision mediump float;
uniform float uTime;
uniform vec2 uPointer;
uniform vec2 uResolution;
varying vec2 vUv;

float hash(vec2 p) {
  p = fract(p * vec2(123.34, 456.21));
  p += dot(p, p + 45.32);
  return fract(p.x * p.y);
}

float noise(vec2 p) {
  vec2 i = floor(p);
  vec2 f = fract(p);
  float a = hash(i);
  float b = hash(i + vec2(1.0, 0.0));
  float c = hash(i + vec2(0.0, 1.0));
  float d = hash(i + vec2(1.0, 1.0));
  vec2 u = f * f * (3.0 - 2.0 * f);
  return mix(a, b, u.x) + (c - a) * u.y * (1.0 - u.x) + (d - b) * u.x * u.y;
}

void main() {
  float aspect = uResolution.x / max(uResolution.y, 1.0);
  vec2 p = vec2(vUv.x * aspect, vUv.y);
  // Paper fibers in two directions, fixed in place.
  float fibers = noise(p * vec2(38.0, 5.0)) * 0.6 + noise(p * vec2(5.0, 38.0)) * 0.4;
  // Fine static grain.
  float grain = hash(floor(gl_FragCoord.xy / 1.5)) - 0.5;
  // A soft vertical fold that drifts slowly and leans toward the pointer.
  float foldX = 0.5 + (uPointer.x - 0.5) * 0.12 + sin(uTime * 0.12) * 0.015;
  float fold = exp(-pow((vUv.x - foldX) * 9.0, 2.0));
  // Raking light that follows the pointer.
  float light = 1.0 - smoothstep(0.0, 0.85, distance(vUv, uPointer));
  float lift = 0.035 * (fibers - 0.5) + 0.02 * grain + 0.045 * fold + 0.07 * light;
  gl_FragColor = vec4(vec3(0.94, 0.90, 0.82), clamp(0.03 + lift, 0.0, 0.16));
}
`;

type Mode = "idle" | "webgl" | "static";

/**
 * A subtle paper-grain and light-fold layer behind the home ticket. Falls back to the static paper
 * texture when WebGL is unavailable, the visitor prefers reduced motion, or the device reports little
 * memory. Pauses while the tab is hidden and releases the GL context on unmount.
 */
export function PaperShader() {
  const host = useRef<HTMLDivElement>(null);
  const [mode, setMode] = useState<Mode>("idle");

  useEffect(() => {
    let cancelled = false;
    let teardown: (() => void) | null = null;

    const start = async () => {
      const memory = (navigator as Navigator & { deviceMemory?: number }).deviceMemory;
      if (prefersReducedMotion() || (memory !== undefined && memory < 4)) {
        setMode("static");
        return;
      }

      let ogl: typeof import("ogl");
      try {
        ogl = await import("ogl");
      } catch (err) {
        console.warn("[PriceQuorum] the paper shader could not load", err);
        if (!cancelled) setMode("static");
        return;
      }
      if (cancelled || !host.current) return;
      const container = host.current;

      let renderer: InstanceType<typeof ogl.Renderer>;
      try {
        renderer = new ogl.Renderer({
          dpr: Math.min(window.devicePixelRatio || 1, MAX_DPR),
          alpha: true,
          premultipliedAlpha: false,
          antialias: false,
          powerPreference: "low-power",
        });
      } catch {
        setMode("static");
        return;
      }
      const gl = renderer.gl;
      if (!gl) {
        setMode("static");
        return;
      }
      gl.clearColor(0, 0, 0, 0);

      const program = new ogl.Program(gl, {
        vertex: VERTEX,
        fragment: FRAGMENT,
        transparent: true,
        uniforms: { uTime: { value: 0 }, uPointer: { value: [0.5, 0.6] }, uResolution: { value: [1, 1] } },
      });
      const mesh = new ogl.Mesh(gl, { geometry: new ogl.Triangle(gl), program });

      const pointer = { x: 0.5, y: 0.6 };
      const target = { x: 0.5, y: 0.6 };
      const started = performance.now();
      let frame = 0;

      const resize = () => {
        renderer.setSize(window.innerWidth, window.innerHeight);
        program.uniforms.uResolution.value = [window.innerWidth, window.innerHeight];
      };
      const onPointer = (event: PointerEvent) => {
        target.x = event.clientX / window.innerWidth;
        target.y = 1 - event.clientY / window.innerHeight;
      };
      const tick = (now: number) => {
        pointer.x += (target.x - pointer.x) * 0.06;
        pointer.y += (target.y - pointer.y) * 0.06;
        program.uniforms.uTime.value = (now - started) / 1000;
        program.uniforms.uPointer.value = [pointer.x, pointer.y];
        renderer.render({ scene: mesh });
        frame = requestAnimationFrame(tick);
      };
      const onVisibility = () => {
        cancelAnimationFrame(frame);
        if (!document.hidden) frame = requestAnimationFrame(tick);
      };

      const canvas = gl.canvas as HTMLCanvasElement;
      canvas.setAttribute("aria-hidden", "true");
      canvas.style.display = "block";
      container.appendChild(canvas);
      resize();
      window.addEventListener("resize", resize);
      window.addEventListener("pointermove", onPointer);
      document.addEventListener("visibilitychange", onVisibility);
      if (!document.hidden) frame = requestAnimationFrame(tick);
      setMode("webgl");

      teardown = () => {
        cancelAnimationFrame(frame);
        window.removeEventListener("resize", resize);
        window.removeEventListener("pointermove", onPointer);
        document.removeEventListener("visibilitychange", onVisibility);
        gl.getExtension("WEBGL_lose_context")?.loseContext();
        canvas.remove();
      };
    };

    // Waits for the preloader to leave, so the shader never competes with its animation on a slow device.
    const PRELOADER = '[role="status"][aria-label="Loading PriceQuorum"]';
    let observer: MutationObserver | null = null;
    const whenPreloaderGone = () => {
      if (cancelled) return;
      if (!document.querySelector(PRELOADER)) {
        void start();
        return;
      }
      observer = new MutationObserver(() => {
        if (document.querySelector(PRELOADER)) return;
        observer?.disconnect();
        observer = null;
        void start();
      });
      observer.observe(document.body, { childList: true, subtree: true });
    };
    const timer = window.setTimeout(whenPreloaderGone, START_DELAY_MS);

    return () => {
      cancelled = true;
      window.clearTimeout(timer);
      observer?.disconnect();
      teardown?.();
    };
  }, []);

  return (
    <div
      ref={host}
      aria-hidden="true"
      data-paper-shader={mode}
      className="pointer-events-none fixed inset-0 z-[5] mix-blend-soft-light"
    >
      {mode === "static" ? <div className="texture-paper h-full w-full opacity-[0.07]" /> : null}
    </div>
  );
}
