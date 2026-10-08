import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { profileApi, type Academics, type ParsedCard, type Profile, type SubjectRow, type Backlog } from '../../api/v2';
import CountUp from '../../components/bits/CountUp';
import st from './v2.module.css';
import s from '../../design/shared.module.css';

const GRADES = ['S', 'A+', 'A', 'B+', 'B', 'C+', 'C', 'D', 'P', 'F', 'FE', 'AB'];

export default function AcademicsPage() {
  const [profile, setProfile] = useState<Profile | null>(null);
  const [subjects, setSubjects] = useState<{ current: SubjectRow[]; backlogs: Backlog[] } | null>(null);
  const [acad, setAcad] = useState<Academics | null>(null);
  const [picked, setPicked] = useState<Set<string>>(new Set());
  const [busy, setBusy] = useState<string | null>(null);
  const [message, setMessage] = useState<string | null>(null);

  const load = useCallback(async () => {
    const [p, a] = await Promise.all([profileApi.get(), profileApi.academics()]);
    setProfile(p);
    setAcad(a);
    if (p.branch && p.semester) setSubjects(await profileApi.subjects());
  }, []);

  useEffect(() => {
    load().catch(() => setMessage('Could not reach the backend.'));
  }, [load]);

  const save = async (patch: { branch?: string; semester?: number; target_cgpa?: number }) => {
    setBusy('profile');
    try {
      setProfile(await profileApi.save(patch));
      await load();
    } catch (e: any) {
      setMessage(e?.response?.data?.detail ?? 'Could not save');
    } finally {
      setBusy(null);
    }
  };

  const addPicked = async (codes: string[]) => {
    if (!codes.length) return;
    setBusy('add');
    try {
      const r = await profileApi.addSubjects(codes);
      setMessage(`Started for ${r.started.map((x) => x.code).join(', ')}: syllabus → papers → reading → notes. Progress is under Jobs.`);
      setPicked(new Set());
      await load();
    } finally {
      setBusy(null);
    }
  };

  if (!profile) return <span className="spinner" />;

  return (
    <div className={st.page}>
      <header className={st.homeHead}>
        <div className="caps">Academics</div>
        <h1 className={st.homeTitle}>Your semester</h1>
        <p className={st.homeLede}>
          Pick your branch and semester and your subjects come from the official 2019-scheme curriculum. Import your grade card for SGPA, CGPA and
          backlogs. No KTU login is needed — the app never asks for your portal password.
        </p>
      </header>

      {message && <div className={`card ${st.cardPad} ${st.notice}`}>{message}</div>}

      <section className={`card ${st.cardPad} ${st.profileRow}`}>
        <label className={s.field}>
          <span>Branch</span>
          <select className={s.select} value={profile.branch ?? ''} disabled={busy === 'profile'} onChange={(e) => save({ branch: e.target.value })}>
            <option value="" disabled>Choose…</option>
            {profile.known_branches.map((b) => <option key={b} value={b}>{b}</option>)}
          </select>
        </label>
        <label className={s.field}>
          <span>Current semester</span>
          <select className={s.select} value={profile.semester ?? ''} disabled={busy === 'profile'} onChange={(e) => save({ semester: Number(e.target.value) })}>
            <option value="" disabled>Choose…</option>
            {[1, 2, 3, 4, 5, 6, 7, 8].map((n) => <option key={n} value={n}>S{n}</option>)}
          </select>
        </label>
        <label className={s.field}>
          <span>Target CGPA</span>
          <input className={s.input} type="number" step="0.1" min="5" max="10" defaultValue={profile.target_cgpa ?? ''}
            onBlur={(e) => e.target.value && save({ target_cgpa: Number(e.target.value) })} placeholder="e.g. 8.5" />
        </label>
        <div className={st.muted}>{busy === 'profile' ? 'Fetching the curriculum…' : `Scheme ${profile.scheme} · ${profile.university}`}</div>
      </section>

      {subjects && (
        <section className={st.stack}>
          <div className={st.row}>
            <div>
              <div className={st.sectionTitle}>S{profile.semester} subjects · {profile.branch}</div>
              <div className={st.sectionHint}>Adding a subject builds its topic list from the syllabus, then finds and reads its past papers and notes automatically.</div>
            </div>
            <span className={st.spacer} />
            <button className={s.btnPrimary} disabled={!picked.size || busy === 'add'} onClick={() => addPicked([...picked])}>
              {busy === 'add' ? 'Starting…' : `Add ${picked.size || ''} & fetch papers + notes`}
            </button>
          </div>
          <div className={`card ${st.tableCard}`}>
            <table className={st.table}>
              <thead><tr><th /><th>Code</th><th>Course</th><th>Credits</th><th>Status</th></tr></thead>
              <tbody>
                {subjects.current.map((c) => (
                  <tr key={c.code} style={c.theory ? undefined : { opacity: 0.55 }}>
                    <td>
                      {c.theory && !c.added && (
                        <input type="checkbox" aria-label={`Add ${c.code}`} checked={picked.has(c.code)}
                          onChange={(e) => setPicked((cur) => { const n = new Set(cur); if (e.target.checked) n.add(c.code); else n.delete(c.code); return n; })} />
                      )}
                    </td>
                    <td className={st.mono}>{c.code}</td>
                    <td>{c.title}</td>
                    <td className={st.num}>{c.credits ?? '—'}</td>
                    <td>
                      {c.added ? (
                        <Link to={`/courses/${c.code}`}>{c.papers ?? 0} paper{c.papers === 1 ? '' : 's'}{c.provisional ? ' · topics pending' : ''} →</Link>
                      ) : c.theory ? <span className={st.muted}>not added</span> : <span className={st.muted}>lab / non-credit</span>}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </section>
      )}

      {acad && <Summary acad={acad} onAdd={addPicked} busy={busy === 'add'} />}

      <GradeCardImport onSaved={load} />
    </div>
  );
}

function Summary({ acad, onAdd, busy }: { acad: Academics; onAdd: (codes: string[]) => void; busy: boolean }) {
  if (!acad.records.length) {
    return (
      <section className={`card ${st.empty}`}>
        <h2 className={st.emptyTitle}>No grades yet</h2>
        <p>Import a grade card below (the PDF you download from the KTU portal, or a screenshot) to see SGPA, CGPA and backlogs.</p>
      </section>
    );
  }
  const maxSgpa = 10;
  return (
    <section className={st.stack}>
      <div className={st.sectionTitle}>Results</div>
      <div className={st.stats}>
        <div className={`card ${st.stat}`}>
          <div className={`display-num ${st.statValue}`}>{acad.cgpa != null ? <CountUp to={acad.cgpa} duration={1} /> : '—'}</div>
          <div className={st.statLabel}>CGPA</div>
          <div className={st.statSub}>{acad.credits_earned} of {acad.credits_registered} credits earned</div>
        </div>
        <div className={`card ${st.stat}`}>
          <div className={`display-num ${st.statValue}`}>{acad.backlogs.length}</div>
          <div className={st.statLabel}>Backlogs</div>
          <div className={st.statSub}>{acad.backlogs.reduce((a, b) => a + b.credits, 0)} credits to clear</div>
        </div>
        {acad.target && (
          <div className={`card ${st.stat}`}>
            <div className={`display-num ${st.statValue}`}>{acad.target.needed_sgpa ?? '—'}</div>
            <div className={st.statLabel}>SGPA needed in S{acad.target.next_semester}</div>
            <div className={st.statSub}>to reach CGPA {acad.target.target_cgpa}{acad.target.needed_sgpa && acad.target.needed_sgpa > 10 ? ' — not reachable this semester' : ''}</div>
          </div>
        )}
      </div>
      <div className={`card ${st.cardPad}`}>
        <div className="caps" style={{ marginBottom: 8 }}>SGPA by semester</div>
        {acad.semesters.map((sem) => (
          <div key={sem.semester} className={st.barRow}>
            <span className={st.barName}>S{sem.semester} · {sem.courses} courses · {sem.credits_earned}/{sem.credits_registered} credits</span>
            <span className={st.barTrack}><span className={st.barFill} style={{ width: `${((sem.sgpa ?? 0) / maxSgpa) * 100}%` }} /></span>
            <span className={st.barValue}>{sem.sgpa ?? '—'}</span>
          </div>
        ))}
      </div>
      {acad.backlogs.length > 0 && (
        <div className={`card ${st.tableCard}`}>
          <table className={st.table}>
            <thead><tr><th>Backlog</th><th>Course</th><th>Sem</th><th>Credits</th><th>Last grade</th><th>Attempts</th><th /></tr></thead>
            <tbody>
              {acad.backlogs.map((b) => (
                <tr key={b.course_code}>
                  <td className={st.mono}>{b.course_code}</td><td>{b.title ?? '—'}</td><td className={st.num}>{b.semester ?? '—'}</td>
                  <td className={st.num}>{b.credits}</td><td><span className="badge badge--danger">{b.grade}</span></td><td className={st.num}>{b.attempts}</td>
                  <td><button className={st.linkBtn} disabled={busy} onClick={() => onAdd([b.course_code])}>study this →</button></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </section>
  );
}

function GradeCardImport({ onSaved }: { onSaved: () => void }) {
  const [card, setCard] = useState<ParsedCard | null>(null);
  const [rows, setRows] = useState<ParsedCard['records']>([]);
  const [session, setSession] = useState('');
  const [state, setState] = useState<'idle' | 'reading' | 'saving'>('idle');
  const [error, setError] = useState<string | null>(null);

  const upload = async (file: File) => {
    setState('reading');
    setError(null);
    try {
      const c = await profileApi.uploadGradeCard(file);
      setCard(c);
      setRows(c.records);
      setSession(c.session ?? '');
      if (!c.records.length) setError('No course lines with grades were recognised. Check the file, or add rows by hand.');
    } catch (e: any) {
      setError(e?.response?.data?.detail ?? 'Could not read the file');
    } finally {
      setState('idle');
    }
  };

  const saveAll = async () => {
    setState('saving');
    try {
      await profileApi.saveRecords(rows.map((r) => ({ ...r, session_label: session || null })), 'grade_card', card?.source_sha);
      setCard(null);
      setRows([]);
      onSaved();
    } finally {
      setState('idle');
    }
  };

  const update = (k: number, patch: Partial<ParsedCard['records'][number]>) => setRows((cur) => cur.map((r, i) => (i === k ? { ...r, ...patch } : r)));

  return (
    <section className={st.stack}>
      <div>
        <div className={st.sectionTitle}>Import a grade card</div>
        <div className={st.sectionHint}>PDF or screenshot of your result. It is read on this computer (text layer or local OCR); you check every row before saving.</div>
      </div>
      <div className={st.row}>
        <input type="file" accept="application/pdf,image/png,image/jpeg" disabled={state !== 'idle'}
          onChange={(e) => e.target.files?.[0] && upload(e.target.files[0])} />
        {state === 'reading' && <span className={st.muted}>Reading… (a scan takes about 30 s per page)</span>}
        <button className={s.btnGhost} onClick={() => { setCard(card ?? { source_sha: '', records: [], text_chars: 0 }); setRows((r) => [...r, { course_code: '', grade: 'A' }]); }}>
          Add a row by hand
        </button>
      </div>
      {error && <div className={st.flagNote}>{error}</div>}
      {card && (
        <div className={`card ${st.tableCard}`}>
          <div className={st.cardPad} style={{ paddingBottom: 0 }}>
            <label className={st.muted}>Exam session <input className={s.input} value={session} onChange={(e) => setSession(e.target.value)} placeholder="e.g. December 2022" /></label>
          </div>
          <table className={st.table}>
            <thead><tr><th>Code</th><th>Course</th><th>Grade</th><th>Credits</th><th>Sem</th><th /></tr></thead>
            <tbody>
              {rows.map((r, k) => (
                <tr key={k}>
                  <td><input className={s.input} style={{ width: 90 }} value={r.course_code} onChange={(e) => update(k, { course_code: e.target.value.toUpperCase() })} /></td>
                  <td><input className={s.input} value={r.title ?? ''} onChange={(e) => update(k, { title: e.target.value })} /></td>
                  <td>
                    <select className={s.select} value={r.grade} onChange={(e) => update(k, { grade: e.target.value })}>
                      {GRADES.map((g) => <option key={g}>{g}</option>)}
                    </select>
                  </td>
                  <td><input className={s.input} style={{ width: 60 }} type="number" value={r.credits ?? ''} placeholder="auto" onChange={(e) => update(k, { credits: e.target.value ? Number(e.target.value) : null })} /></td>
                  <td><input className={s.input} style={{ width: 50 }} type="number" value={r.semester ?? ''} onChange={(e) => update(k, { semester: e.target.value ? Number(e.target.value) : null })} /></td>
                  <td><button className={st.linkBtn} onClick={() => setRows((cur) => cur.filter((_, i) => i !== k))}>remove</button></td>
                </tr>
              ))}
            </tbody>
          </table>
          <div className={st.cardPad}>
            <button className={s.btnPrimary} disabled={!rows.length || rows.some((r) => !r.course_code) || state !== 'idle'} onClick={saveAll}>
              {state === 'saving' ? 'Saving…' : `Save ${rows.length} result${rows.length === 1 ? '' : 's'}`}
            </button>
            <span className={st.muted} style={{ marginLeft: 12 }}>Credits left blank are taken from the curriculum.</span>
          </div>
        </div>
      )}
    </section>
  );
}
