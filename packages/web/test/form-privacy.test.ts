// @vitest-environment jsdom

import { afterEach, beforeEach, describe, expect, it } from 'vitest';

import { FormAnalyticsModule } from '../src/modules/form-analytics';

type Emitted = { event: string; props: Record<string, unknown> };

let module: FormAnalyticsModule | null = null;

beforeEach(() => {
  document.body.innerHTML = '';
});

afterEach(() => {
  module?.destroy();
  module = null;
});

function setupForm(): { emitted: Emitted[]; form: HTMLFormElement } {
  document.body.innerHTML = `
    <form id="signup">
      <input name="email" type="email" />
      <input name="password" type="password" />
      <textarea name="notes"></textarea>
    </form>
  `;
  const emitted: Emitted[] = [];
  module = new FormAnalyticsModule(
    { onTrack: (event, props) => emitted.push({ event, props }) },
    { autoDiscover: false },
  );
  const form = document.getElementById('signup') as HTMLFormElement;
  module.trackForm(form);
  return { emitted, form };
}

function fire(el: Element, type: string): void {
  el.dispatchEvent(new Event(type, { bubbles: true }));
}

describe('form analytics privacy', () => {
  it('captures metadata only — typed values never appear in any payload', () => {
    const { emitted, form } = setupForm();
    const email = form.querySelector<HTMLInputElement>('[name=email]')!;
    const password = form.querySelector<HTMLInputElement>('[name=password]')!;

    email.value = 'person@secret-domain.example';
    password.value = 'hunter2-super-secret';
    fire(email, 'focusin');
    fire(email, 'input');
    fire(email, 'focusout');
    fire(password, 'focusin');
    fire(password, 'input');

    expect(emitted.length).toBeGreaterThan(0);
    const serialized = JSON.stringify(emitted);
    expect(serialized).not.toContain('person@secret-domain.example');
    expect(serialized).not.toContain('hunter2-super-secret');
    for (const { event, props } of emitted) {
      expect(event).toBe('form_field');
      expect(props).not.toHaveProperty('value');
      expect(props).not.toHaveProperty('defaultValue');
      expect(props).not.toHaveProperty('checked');
      expect(Object.keys(props).sort()).toEqual(
        ['action', 'fieldName', 'fieldType', 'formId', 'timestamp'],
      );
    }
  });

  it('emits structural metadata for the interaction', () => {
    const { emitted, form } = setupForm();
    const email = form.querySelector<HTMLInputElement>('[name=email]')!;

    fire(email, 'focusin');

    expect(emitted[0].props).toMatchObject({
      fieldName: 'email',
      fieldType: 'email',
      action: 'focus',
      formId: 'signup',
    });
  });
});
