import { useCallback, useEffect, useRef, useState } from 'react';
import { libraryApi, type LibraryState } from '../../api/v2';
import JobCard from './JobCard';
import st from '../../pages/v2/v2.module.css';
import s from '../../design/shared.module.css';

const ACCEPT = /\.(pdf|zip|png|jpe?g|webp)$/i;
const SUGGESTIONS = ['My semester', 'KTU AI & Data Science (ADT)', 'KTU S4 CSE', 'MAT204'];

/**
 * Bring in question papers for any subject: a wide agy search, or files / a ZIP / a whole folder.
 * Nothing asks which subject — the code printed on each paper decides where it is filed.
 */
export default function GatherPanel({ onFiled }: { onFiled?: () => void }) {
  const files = useRef<HTMLInputElement>(null);
  const folder = useRef<HTMLInputElement>(null);
  const [lib, setLib] = useState<LibraryState | null>(null);
  const [query, setQuery] = useState('');
  const [drag, setDrag] = useState(false);
  const [note, setNote] = useState<{ error?: boolean; text: string } | null>(null);
  const [uploading, setUploading] = useState(false);
  const [jobId, setJobId] = useState<string | null>(null);
  const [assign, setAssign] = useState<Record<string, string>>({});

  const load = useCallback(() => {
    libraryApi
      .get()
      .then((l) => {
        setLib(l);
        const live = l.jobs.find((j) => j.status === 'running' || j.status === 'queued');
        if (live) setJobId((cur) => cur ?? live.id);
      })
      .catch(() => setLib(null));
  }, []);

  useEffect(() => {
    load();
    folder.current?.setAttribute('webkitdirectory', ''); // not in React's typings
  }, [load]);

  const send = async (list: FileList | null) => {
    const picked = Array.from(list ?? []).filter((f) => ACCEPT.test(f.name));
    if (!picked.length) {
      setNote({ error: true, text: 'No PDF, photo or ZIP files in that selection.' });
      return;
    }
    setUploading(true);
    setNote({ text: `Uploading ${picked.length} file${picked.length > 1 ? 's' : ''}…` });
    try {
      const r = await libraryApi.upload(picked);
      const parts = [`${r.added} new`];
      if (r.duplicates) parts.push(`${r.duplicates} already had`);
      if (r.skipped.length) parts.push(`${r.skipped.length} skipped (not PDF/photo)`);
      setNote({ text: parts.join(' · ') + (r.added ? ' — now finding each paper’s subject' : '') });
      if (r.job) setJobId(r.job.id);
    } catch (e) {
      setNote({ error: true, text: e instanceof Error ? e.message : 'Upload failed' });
    } finally {
      setUploading(false);
    }
  };

  const search = async () => {
    try {
      const q = query.trim();
      const j = await libraryApi.search(q && q !== 'My semester' ? q : undefined);
      setJobId(j.id);
      setNote(null);
    } catch (e) {
      setNote({ error: true, text: e instanceof Error ? e.message : 'Search could not start' });
    }
  };

  const adopt = async (code: string, sha?: string) => {
    try {
      const r = await libraryApi.adopt(code, sha);
      setNote({ text: `${r.moved} paper${r.moved > 1 ? 's' : ''} moved to ${r.code}; reading them now.` });
      load();
      onFiled?.();
    } catch (e) {
      setNote({ error: true, text: e instanceof Error ? e.message : 'Could not add that subject' });
    }
  };

  const addAll = async () => {
    for (const g of lib?.other_subjects ?? []) await adopt(g.code);
  };

  const showLibrary = lib && (lib.other_subjects.length > 0 || lib.unidentified.length > 0 || lib.pending > 0);

  return (
    <section className={st.stack}>
      <div>
        <div className={st.sectionTitle}>Bring in question papers</div>
        <div className={st.sectionHint}>
          For any subject. You don’t pick one: the subject code printed on each paper decides where it goes, and new
          subjects are added for you.
        </div>
      </div>

      <div className={st.gatherGrid}>
        <div className={`card ${st.gatherCard}`}>
          <div className={st.gatherHead}>
            <span className={st.gatherNo}>01</span>
            <span className={st.gatherTitle}>Search the web</span>
          </div>
          <p className={st.muted}>
            agy runs six or more searches and every question paper found is downloaded, whatever its subject. Leave the
            box empty to search for your semester.
          </p>
          <div className={st.chips}>
            {SUGGESTIONS.map((q) => (
              <button key={q} type="button" className={st.chip} onClick={() => setQuery(q)}>{q}</button>
            ))}
          </div>
          <form className={st.gatherForm} onSubmit={(e) => { e.preventDefault(); search(); }}>
            <input className={s.input} value={query} onChange={(e) => setQuery(e.target.value)}
              placeholder="Subject code, name or branch" aria-label="What to search for" />
            <button className={s.btnPrimary} type="submit">Search</button>
          </form>
        </div>

        <div className={`card ${st.gatherCard}`}>
          <div className={st.gatherHead}>
            <span className={st.gatherNo}>02</span>
            <span className={st.gatherTitle}>Upload what you have</span>
          </div>
          <div
            className={`${st.drop} ${drag ? st.dropActive : ''}`}
            onDragOver={(e) => { e.preventDefault(); setDrag(true); }}
            onDragLeave={() => setDrag(false)}
            onDrop={(e) => { e.preventDefault(); setDrag(false); send(e.dataTransfer.files); }}
          >
            <svg className={st.dropIcon} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.5" aria-hidden="true">
              <path d="M12 16V4m0 0-4.5 4.5M12 4l4.5 4.5M4 15v3.5A1.5 1.5 0 0 0 5.5 20h13a1.5 1.5 0 0 0 1.5-1.5V15" strokeLinecap="round" strokeLinejoin="round" />
            </svg>
            <div className={st.dropText}>Drop PDFs, photos, a ZIP or a folder here</div>
            <div className={st.row}>
              <button className={s.btnSecondary} disabled={uploading} onClick={() => files.current?.click()}>Choose files or ZIP</button>
              <button className={s.btnSecondary} disabled={uploading} onClick={() => folder.current?.click()}>Choose folder</button>
            </div>
          </div>
          <input ref={files} type="file" multiple accept=".pdf,.zip,image/*" hidden
            onChange={(e) => { send(e.target.files); e.target.value = ''; }} />
          <input ref={folder} type="file" multiple hidden onChange={(e) => { send(e.target.files); e.target.value = ''; }} />
        </div>
      </div>

      {note && (
        <div className={note.error ? st.errorText : st.muted} role="status">
          {uploading && <span className="spinner" />} {note.text}
        </div>
      )}
      {jobId && <JobCard key={jobId} jobId={jobId} compact onDone={() => { load(); onFiled?.(); }} />}

      {showLibrary && (
        <div className={`card ${st.libraryCard}`}>
          <div className={st.row}>
            <div className="caps">In the library, not filed under a subject yet</div>
            <span className={st.spacer} />
            {lib.other_subjects.length > 1 && (
              <button className={`${s.btnSecondary} ${s.btnSm}`} onClick={addAll}>Add all {lib.other_subjects.length} subjects</button>
            )}
          </div>
          {lib.pending > 0 && <div className={st.muted}>{lib.pending} file{lib.pending > 1 ? 's' : ''} waiting to be read.</div>}
          {lib.other_subjects.map((g) => (
            <div key={g.code} className={st.libraryRow}>
              <span className={st.courseCode}>{g.code}</span>
              <span className={st.libraryTitle}>{g.title ?? 'Title not read'}</span>
              <span className={st.muted}>{g.papers} paper{g.papers > 1 ? 's' : ''}</span>
              <span className={st.spacer} />
              <button className={`${s.btnSecondary} ${s.btnSm}`} onClick={() => adopt(g.code)}>Add subject</button>
            </div>
          ))}
          {lib.unidentified.map((d) => (
            <form key={d.sha256} className={st.libraryRow}
              onSubmit={(e) => { e.preventDefault(); if (assign[d.sha256]) adopt(assign[d.sha256], d.sha256); }}>
              <a href={d.file_url} target="_blank" rel="noreferrer" className={st.libraryTitle}>{d.name ?? d.sha256.slice(0, 10)}</a>
              <span className={st.muted}>no subject code readable</span>
              <span className={st.spacer} />
              <input className={`${s.input} ${st.codeInput}`} placeholder="Code" value={assign[d.sha256] ?? ''}
                onChange={(e) => setAssign((a) => ({ ...a, [d.sha256]: e.target.value.toUpperCase() }))} aria-label="Subject code" />
              <button className={`${s.btnSecondary} ${s.btnSm}`} type="submit">File it</button>
            </form>
          ))}
        </div>
      )}
    </section>
  );
}
