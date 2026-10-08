import { useEffect, useMemo, useState } from 'react';
import { v2, type SourceCandidate, type SourceDocument } from '../../../api/v2';
import { useCourse } from '../courseContext';
import CoverageStrip from './CoverageStrip';
import st from '../v2.module.css';

const MONTHS = ['', 'Jan', 'Feb', 'Mar', 'Apr', 'May', 'Jun', 'Jul', 'Aug', 'Sep', 'Oct', 'Nov', 'Dec'];
const DOC_BADGE: Record<string, string> = {
  fetched: 'badge badge--neutral', identified: 'badge badge--info', transcribed: 'badge badge--success',
  rejected: 'badge badge--danger', duplicate: 'badge badge--warning', other_course: 'badge badge--warning',
  unidentified: 'badge badge--warning',
};
const CAND_BADGE: Record<string, string> = {
  fetched: 'badge badge--success', duplicate: 'badge badge--warning', failed: 'badge badge--danger',
  skipped: 'badge badge--neutral', new: 'badge badge--info',
};

function origin(found: string) {
  if (found === 'upload') return 'Uploaded';
  if (found.startsWith('dspace:')) return `DSpace ${found.slice(7)}`;
  if (found.startsWith('page:')) return found.slice(5);
  if (found.startsWith('agy:')) return `agy search ${found.slice(4).replace('>page', ' → page')}`;
  return found;
}

export default function SourcesTab() {
  const { course, coverage, version } = useCourse();
  const [data, setData] = useState<{ candidates: SourceCandidate[]; documents: SourceDocument[] } | null>(null);
  const [filter, setFilter] = useState<string>('all');

  useEffect(() => {
    v2.sources(course.code).then(setData).catch(() => setData({ candidates: [], documents: [] }));
  }, [course.code, version]);

  const counts = useMemo(() => {
    const c: Record<string, number> = {};
    for (const x of data?.candidates ?? []) c[x.status] = (c[x.status] ?? 0) + 1;
    return c;
  }, [data]);

  if (!data) return <span className="spinner" />;
  const cands = filter === 'all' ? data.candidates : data.candidates.filter((c) => c.status === filter);

  return (
    <>
      {coverage && (
        <section className={st.stack}>
          <div>
            <div className={st.sectionTitle}>Coverage</div>
            <div className={st.sectionHint}>Expected exam windows since the scheme's first exam, matched by the session printed on each paper — not by the source's label.</div>
          </div>
          <CoverageStrip coverage={coverage} />
        </section>
      )}

      <section className={st.stack}>
        <div>
          <div className={st.sectionTitle}>Documents ({data.documents.length})</div>
          <div className={st.sectionHint}>Every downloaded file, stored once per content hash. "Claimed" is what the source said; "On the paper" is what the header says.</div>
        </div>
        <div className={`card ${st.tableCard}`}>
          <table className={st.table}>
            <thead>
              <tr><th>Source</th><th>Claimed</th><th>On the paper</th><th>QP code</th><th>Pages</th><th>Status</th><th /></tr>
            </thead>
            <tbody>
              {data.documents.map((d) => {
                const id = d.identified ?? {};
                const onPaper = id.month && id.year ? `${MONTHS[id.month]} ${id.year}` : '—';
                const mismatch = d.label_claimed && id.year && !d.label_claimed.toLowerCase().includes(String(id.year));
                return (
                  <tr key={d.sha256}>
                    <td>{origin(d.origin)}<div className={st.mono} title={d.sha256}>{d.sha256.slice(0, 10)}</div></td>
                    <td className={st.wrapCell}>{d.label_claimed ?? '—'}</td>
                    <td>{onPaper}{mismatch && <span className="badge badge--danger" style={{ marginLeft: 6 }}>differs</span>}{id.rotated && <div className={st.muted}>scan was upside down</div>}{id.session_from && <div className={st.muted}>from {id.session_from}</div>}</td>
                    <td className={st.mono}>{id.qp_code ?? '—'}</td>
                    <td className={st.num}>{d.pages ?? '—'}</td>
                    <td><span className={DOC_BADGE[d.status] ?? 'badge badge--neutral'}>{d.status}</span>{id.reject_reason && <div className={st.muted}>{id.reject_reason}</div>}</td>
                    <td><a href={d.file_url} target="_blank" rel="noreferrer">open</a></td>
                  </tr>
                );
              })}
              {data.documents.length === 0 && <tr><td colSpan={7} className={st.muted}>Nothing downloaded yet — run Find papers.</td></tr>}
            </tbody>
          </table>
        </div>
      </section>

      <section className={st.stack}>
        <div className={st.row}>
          <div>
            <div className={st.sectionTitle}>Candidates ({data.candidates.length})</div>
            <div className={st.sectionHint}>Links found by connectors and agy searches. Nothing counts until it is downloaded and verified.</div>
          </div>
          <span className={st.spacer} />
          <div className={st.kButtons}>
            {['all', 'fetched', 'duplicate', 'skipped', 'failed'].map((f) => (
              <button key={f} className={filter === f ? st.kBtnActive : st.kBtn} onClick={() => setFilter(f)}>
                {f} {f === 'all' ? data.candidates.length : counts[f] ?? 0}
              </button>
            ))}
          </div>
        </div>
        <div className={`card ${st.tableCard}`}>
          <table className={st.table}>
            <thead><tr><th>Found by</th><th>Label</th><th>Status</th><th>URL</th></tr></thead>
            <tbody>
              {cands.map((c) => (
                <tr key={c.id}>
                  <td>{origin(c.found_by)}</td>
                  <td className={st.wrapCell}>{c.label ?? '—'}</td>
                  <td><span className={CAND_BADGE[c.status]}>{c.status}</span>{c.reason && <div className={st.muted}>{c.reason}</div>}</td>
                  <td className={st.wrapCell}><a href={c.url} target="_blank" rel="noreferrer" className={st.mono}>{shortUrl(c.url)}</a></td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>
    </>
  );
}

function shortUrl(u: string) {
  try {
    const x = new URL(u);
    const path = decodeURIComponent(x.pathname);
    return `${x.hostname.replace(/^www\./, '')}${path.length > 48 ? path.slice(0, 46) + '…' : path}`;
  } catch {
    return u.slice(0, 60);
  }
}

