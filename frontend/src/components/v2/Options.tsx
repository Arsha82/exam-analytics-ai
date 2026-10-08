import MathText from './MathText';
import st from '../../pages/v2/v2.module.css';

const LETTERS = 'abcdefgh';

/** The printed choices of an MCQ question, lettered as on the paper. */
export default function Options({ options }: { options?: string[] | null }) {
  if (!options?.length) return null;
  return (
    <ol className={st.options}>
      {options.map((o, i) => (
        <li key={i}>
          <span className={st.optionLetter}>{LETTERS[i]})</span>
          <MathText text={o} />
        </li>
      ))}
    </ol>
  );
}
