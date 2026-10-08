import { useEffect, useState } from 'react';
import { studyApi, type NoteDoc } from '../../../api/v2';
import { useCourse } from '../courseContext';
import st from '../v2.module.css';
import s from '../../../design/shared.module.css';

export default function NotesTab() {
  const { course, version, runJob, busy } = useCourse();
  const [notes, setNotes] = useState<NoteDoc[] | null>(null);

  useEffect(() => {
    studyApi.notes(course.code).then(setNotes).catch(() => setNotes([]));
  }, [course.code, version]);

  if (!notes) return <span className="spinner" />;
  const groups = [...course.modules.map((m) => ({ key: m.no as number | null, title: `Module ${m.no} · ${m.title}` })),
    { key: null, title: 'Module not detected' }];

  return (
    <>
      <section className={st.stack}>
        <div className={st.row}>
          <div>
            <div className={st.sectionTitle}>Notes ({notes.length})</div>
            <div className={st.sectionHint}>
              Found by agy web searches and page mining, downloaded once, sorted by module (from the link and the PDF's own text).
              They also feed the lessons. Personal study use only.
            </div>
          </div>
          <span className={st.spacer} />
          <button className={s.btnPrimary} disabled={busy} onClick={() => runJob('notes')}>
            {notes.length ? 'Search for more notes' : 'Find notes'}
          </button>
        </div>
      </section>
      {groups.map((g) => {
        const items = notes.filter((n) => (n.module ?? null) === g.key);
        if (!items.length && g.key === null) return null;
        return (
          <section key={String(g.key)} className={st.stack}>
            <div className="caps">{g.title} · {items.length}</div>
            {items.length === 0 ? (
              <div className={st.muted}>Nothing yet for this module.</div>
            ) : (
              <div className={st.noteGrid}>
                {items.map((n) => (
                  <a key={n.sha256} className={`card ${st.note}`} href={n.file_url} target="_blank" rel="noreferrer">
                    <div className={st.noteTitle} title={n.title ?? undefined}>{cleanTitle(n.title, n.module)}</div>
                    <div className={st.muted}>{n.pages ? `${n.pages} pages · ` : ''}{(n.bytes / 1048576).toFixed(1)} MB · {host(n.url)}</div>
                  </a>
                ))}
              </div>
            )}
          </section>
        );
      })}
    </>
  );
}

/** Scraped link text is noisy; describe the file instead: module + what kind of notes. */
function cleanTitle(t: string | null | undefined, module: number | null | undefined) {
  const raw = (t ?? '').replace(/\s+/g, ' ');
  const hints: string[] = [];
  if (/handwritten/i.test(raw)) hints.push('handwritten');
  const set = raw.match(/\bset\s*(\d+)/i);
  if (set) hints.push(`set ${set[1]}`);
  const by = raw.match(/shared by ([A-Z][a-z]+)/);
  if (by) hints.push(`shared by ${by[1]}`);
  if (/\b(ppt|slides)\b/i.test(raw)) hints.push('slides');
  const head = module ? `Module ${module} notes` : 'Notes';
  return hints.length ? `${head} · ${hints.join(' · ')}` : head;
}

function host(u?: string | null) {
  try {
    return u ? new URL(u).hostname.replace(/^www\./, '') : '';
  } catch {
    return '';
  }
}
