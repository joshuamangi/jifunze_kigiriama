// A study session: one card at a time. The server decides what to show and grades the answers;
// this screen only displays cards and sends what the learner typed or tapped.
import { get, post, query } from '../api.js';
import { icon } from '../icons.js';
import { banner, emptyState, errorBanner, field, h, topbar } from '../ui.js';

const GRADES = [['again', 'Again'], ['hard', 'Hard'], ['good', 'Good'], ['easy', 'Easy']];

function whenText(days) {
  if (days <= 0) return 'again today';
  if (days === 1) return 'tomorrow';
  return `in ${days} days`;
}

export default async function study({ params }) {
  const tier = Number(params.get('tier')) === 1 ? 1 : 2;
  const title = tier === 1 ? 'Spelling practice' : 'Vocabulary practice';
  const { cards } = await get(`/api/learn/session${query({ tier })}`);

  const queue = [...cards];
  const total = cards.length;
  let answered = 0;
  let right = 0;
  const bar = h('progress', { class: 'progress', max: String(Math.max(total, 1)), value: '0', 'aria-label': 'Session progress' });
  const label = h('p', { class: 'small muted', 'aria-live': 'polite' });
  const stage = h('div');

  function paintProgress() {
    bar.value = answered;
    label.textContent = `${answered} of ${total} done`;
  }

  async function finish() {
    paintProgress();
    let streak = null;
    try { streak = (await get('/api/learn/summary')).streak_days; } catch { /* the summary is a bonus */ }
    stage.replaceChildren(
      h(
        'div',
        { class: 'card stack' },
        h('h2', { class: 'h1 no-margin' }, 'Session complete'),
        h('p', { class: 'muted no-margin' }, `You answered ${answered} ${answered === 1 ? 'card' : 'cards'}, ${right} right first time.`),
        streak ? h('p', { class: 'row no-margin' }, h('span', { class: 'secondary' }, icon('flame', 20)), `${streak}-day streak`) : null,
        h('a', { class: 'btn btn-primary btn-block', href: '#/learn' }, 'Back to Learn'),
      ),
    );
  }

  function next() {
    paintProgress();
    if (queue.length === 0) return finish();
    show(queue.shift());
  }

  // A card counts as done once answered correctly; a miss goes to the back of the queue.
  function finishCard(card, result, firstTry) {
    if (result.correct) {
      answered += 1;
      if (firstTry) right += 1;
    } else {
      queue.push({ ...card, retry: true });
    }
  }

  // After an answer: say what happened, then continue. A missed card is asked again at the end.
  function feedback(card, result, firstTry) {
    finishCard(card, result, firstTry);
    const message = result.correct ? 'Correct.' : `Not quite. The answer is: ${result.correct_answer}`;
    const go = h('button', { class: 'btn btn-primary btn-block', type: 'button', autofocus: true }, queue.length ? 'Continue' : 'Finish');
    go.addEventListener('click', next);
    stage.append(
      banner(result.correct ? 'info' : 'warn', icon(result.correct ? 'check' : 'x', 20), h('div', null, h('div', { class: 'strong' }, message), h('div', { class: 'small muted' }, `Next review ${whenText(result.interval_days)}.`))),
      go,
    );
    go.focus();
  }

  async function send(card, payload, busy) {
    busy.forEach((el) => { el.disabled = true; });
    try {
      const result = await post('/api/learn/review', { entry_id: card.entry_id, drill: card.drill, ...payload });
      return result;
    } catch (error) {
      busy.forEach((el) => { el.disabled = false; });
      stage.append(errorBanner(error));
      return null;
    }
  }

  function show(card) {
    const firstTry = !card.retry;
    const header = h('p', { class: 'eyebrow' }, card.is_new && firstTry ? 'New card' : card.retry ? 'Try again' : 'Review');
    if (card.drill === 'spell') {
      const answer = field({ label: 'Write it in Kigiriama', id: 'answer', required: true, autocomplete: 'off' });
      const check = h('button', { class: 'btn btn-primary btn-block', type: 'submit' }, 'Check');
      const form = h('form', { novalidate: true }, answer.node, check);
      form.addEventListener('submit', async (event) => {
        event.preventDefault();
        if (!answer.input.value.trim()) return;
        const result = await send(card, { answer: answer.input.value }, [check, answer.input]);
        if (!result) return;
        answer.input.readOnly = true;
        check.remove();
        feedback(card, result, firstTry);
      });
      stage.replaceChildren(header, h('div', { class: 'drill-prompt' }, card.prompt), h('p', { class: 'small muted' }, 'English meaning'), form);
      answer.input.focus();
    } else if (card.drill === 'recognise') {
      const buttons = card.options.map((text) => h('button', { class: 'option', type: 'button' }, text));
      const list = h('div', { class: 'options' }, buttons);
      buttons.forEach((button) =>
        button.addEventListener('click', async () => {
          const result = await send(card, { answer: button.textContent }, buttons);
          if (!result) return;
          button.classList.add(result.correct ? 'option-correct' : 'option-wrong');
          if (!result.correct) buttons.find((b) => b.textContent === result.correct_answer)?.classList.add('option-correct');
          feedback(card, result, firstTry);
        }),
      );
      stage.replaceChildren(header, h('p', { class: 'small muted' }, 'What does this mean?'), h('div', { class: 'drill-prompt' }, card.prompt), list);
    } else {
      const reveal = h('button', { class: 'btn btn-primary btn-block', type: 'button' }, 'Show answer');
      const area = h('div');
      reveal.addEventListener('click', () => {
        reveal.remove();
        const grades = GRADES.map(([, text]) => h('button', { class: 'btn', type: 'button' }, text));
        area.replaceChildren(h('p', { class: 'small muted' }, 'In Kigiriama'), h('div', { class: 'drill-prompt' }, card.answer), h('p', { class: 'small muted' }, 'How well did you remember it?'), h('div', { class: 'grades' }, grades));
        grades.forEach((button, index) =>
          button.addEventListener('click', async () => {
            const result = await send(card, { grade: GRADES[index][0] }, grades);
            if (!result) return;
            area.replaceChildren();
            feedbackRecall(card, result, firstTry);
          }),
        );
      });
      stage.replaceChildren(header, h('p', { class: 'small muted' }, 'English meaning'), h('div', { class: 'drill-prompt' }, card.prompt), reveal, area);
    }
  }

  // Recall is self-graded: every grade moves on; only "Again" brings the card back this session.
  function feedbackRecall(card, result, firstTry) {
    finishCard(card, result, firstTry);
    const go = h('button', { class: 'btn btn-primary btn-block', type: 'button' }, queue.length ? 'Continue' : 'Finish');
    go.addEventListener('click', next);
    stage.append(banner('info', icon(result.correct ? 'check' : 'history', 20), h('div', { class: 'small' }, `Next review ${whenText(result.interval_days)}.`)), go);
    go.focus();
  }

  const page = h('div', null, topbar({ title, back: '#/learn' }));
  const main = h('main', { class: 'screen' });
  page.append(main);
  if (total === 0) {
    main.append(emptyState('check', 'Nothing to study right now. Add entries, or come back when cards are due.'), h('a', { class: 'btn btn-block', href: '#/add' }, 'Add entries'));
    return page;
  }
  main.append(bar, label, stage);
  paintProgress();
  show(queue.shift());
  return page;
}
