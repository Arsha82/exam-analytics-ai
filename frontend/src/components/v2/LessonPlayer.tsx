import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { AnimatePresence, motion, useReducedMotion } from 'motion/react';
import type { Deck } from '../../api/v2';
import MathText from './MathText';
import { renderDisplay } from './math';
import st from './lesson.module.css';

/**
 * Plays a lesson deck: animated slides + narration with the browser's own speech voices
 * (local, no network). Auto-advances when a slide's narration ends; captions mirror it.
 */
export default function LessonPlayer({ deck, courseCode }: { deck: Deck; courseCode: string }) {
  const [i, setI] = useState(0);
  const [playing, setPlaying] = useState(false);
  const [rate, setRate] = useState(1);
  const [voices, setVoices] = useState<SpeechSynthesisVoice[]>([]);
  const [voiceName, setVoiceName] = useState<string>('');
  const [captions, setCaptions] = useState(true);
  const [quizOpen, setQuizOpen] = useState(false);
  const reduce = useReducedMotion();
  const playingRef = useRef(playing);
  useEffect(() => {
    playingRef.current = playing;
  }, [playing]);
  const speechOk = typeof window !== 'undefined' && 'speechSynthesis' in window;
  const slide = deck.slides[i];
  const last = deck.slides.length - 1;

  useEffect(() => {
    if (!speechOk) return;
    const load = () => {
      const v = window.speechSynthesis.getVoices().filter((x) => x.lang.toLowerCase().startsWith('en'));
      setVoices(v);
      setVoiceName((cur) => cur || v.find((x) => /natural|online/i.test(x.name))?.name || v[0]?.name || '');
    };
    load();
    window.speechSynthesis.addEventListener('voiceschanged', load);
    return () => window.speechSynthesis.removeEventListener('voiceschanged', load);
  }, [speechOk]);

  const stop = useCallback(() => {
    if (speechOk) window.speechSynthesis.cancel();
  }, [speechOk]);

  const speak = useCallback(
    (idx: number) => {
      if (!speechOk) return;
      window.speechSynthesis.cancel();
      const u = new SpeechSynthesisUtterance(deck.slides[idx].narration);
      const v = voices.find((x) => x.name === voiceName);
      if (v) u.voice = v;
      u.rate = rate;
      u.onend = () => {
        if (!playingRef.current) return;
        if (idx < last) setI(idx + 1);
        else setPlaying(false);
      };
      window.speechSynthesis.speak(u);
    },
    [deck.slides, last, rate, speechOk, voiceName, voices],
  );

  useEffect(() => {
    if (playing) speak(i);
  }, [i, playing, speak]);

  useEffect(() => () => stop(), [stop]);

  const go = useCallback(
    (to: number) => {
      const next = Math.max(0, Math.min(last, to));
      setI(next);
      if (!playingRef.current) stop();
    },
    [last, stop],
  );

  const toggle = useCallback(() => {
    if (playing) {
      setPlaying(false);
      stop();
    } else {
      setPlaying(true);
    }
  }, [playing, stop]);

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === 'INPUT' || tag === 'TEXTAREA' || tag === 'SELECT') return;
      if (e.key === 'ArrowRight') go(i + 1);
      else if (e.key === 'ArrowLeft') go(i - 1);
      else if (e.key === ' ') {
        e.preventDefault();
        toggle();
      }
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [go, i, toggle]);

  const display = useMemo(() => (slide.latex ? renderDisplay(slide.latex) : null), [slide.latex]);

  return (
    <div className={st.player}>
      <div className={st.stage} aria-live="polite">
        <div className={st.stageMeta}>
          <span>{courseCode} · {slide.kind}</span>
          <span>{i + 1} / {deck.slides.length}</span>
        </div>
        <AnimatePresence mode="wait">
          <motion.div
            key={i}
            className={st.slide}
            initial={reduce ? false : { opacity: 0, x: 24 }}
            animate={{ opacity: 1, x: 0 }}
            exit={reduce ? undefined : { opacity: 0, x: -24 }}
            transition={{ duration: 0.32, ease: [0.22, 1, 0.36, 1] }}
          >
            <h2 className={slide.kind === 'title' ? st.titleHeading : st.heading}>
              <MathText text={slide.heading} />
            </h2>
            {display && (
              <motion.div className={st.display} initial={reduce ? false : { opacity: 0, scale: 0.97 }} animate={{ opacity: 1, scale: 1 }}
                transition={{ delay: 0.12, duration: 0.3 }} dangerouslySetInnerHTML={{ __html: display }} />
            )}
            <ul className={slide.kind === 'steps' ? st.steps : st.bullets}>
              {slide.bullets.map((b, k) => (
                <motion.li key={k} initial={reduce ? false : { opacity: 0, y: 8 }} animate={{ opacity: 1, y: 0 }}
                  transition={{ delay: 0.18 + k * 0.09, duration: 0.28 }}>
                  <MathText text={b} />
                </motion.li>
              ))}
            </ul>
            {slide.ref && <div className={st.ref}>Past paper · {slide.ref}</div>}
          </motion.div>
        </AnimatePresence>
        <div className={st.progressTrack}><div className={st.progressFill} style={{ width: `${((i + 1) / deck.slides.length) * 100}%` }} /></div>
      </div>

      {captions && <p className={st.caption}>{slide.narration}</p>}

      <div className={st.controls}>
        <button className={st.ctrl} onClick={() => go(i - 1)} disabled={i === 0} aria-label="Previous slide">←</button>
        <button className={st.play} onClick={toggle} disabled={!speechOk} aria-label={playing ? 'Pause' : 'Play with narration'}>
          {playing ? 'Pause' : i === 0 ? 'Play lesson' : 'Resume'}
        </button>
        <button className={st.ctrl} onClick={() => go(i + 1)} disabled={i === last} aria-label="Next slide">→</button>
        <div className={st.dots} role="tablist" aria-label="Slides">
          {deck.slides.map((s, k) => (
            <button key={k} role="tab" aria-selected={k === i} title={s.heading} className={k === i ? st.dotActive : st.dot} onClick={() => go(k)} />
          ))}
        </div>
        <span className={st.spacer} />
        <label className={st.small}>
          Speed
          <select value={rate} onChange={(e) => setRate(Number(e.target.value))}>
            {[0.85, 1, 1.15, 1.3].map((r) => <option key={r} value={r}>{r}×</option>)}
          </select>
        </label>
        {voices.length > 0 && (
          <label className={st.small}>
            Voice
            <select value={voiceName} onChange={(e) => setVoiceName(e.target.value)}>
              {voices.map((v) => <option key={v.name} value={v.name}>{v.name.replace(/^Microsoft /, '')}</option>)}
            </select>
          </label>
        )}
        <label className={st.small}>
          <input type="checkbox" checked={captions} onChange={(e) => setCaptions(e.target.checked)} /> Captions
        </label>
      </div>
      {!speechOk && <p className={st.small}>This browser has no speech voices; captions show the narration instead.</p>}

      {deck.quiz.length > 0 && (
        <details className={st.quiz} open={quizOpen} onToggle={(e) => setQuizOpen((e.target as HTMLDetailsElement).open)}>
          <summary>Quick check · {deck.quiz.length} questions</summary>
          <ol>
            {deck.quiz.map((q, k) => (
              <li key={k}>
                <MathText text={q.q} />
                <details className={st.answer}><summary>Answer</summary><MathText text={q.answer} /></details>
              </li>
            ))}
          </ol>
        </details>
      )}
    </div>
  );
}
