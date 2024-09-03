import { Compartment, EditorState } from '@codemirror/state';
import {
  EditorView, keymap, lineNumbers, highlightActiveLine, highlightActiveLineGutter,
  drawSelection, rectangularSelection, dropCursor, highlightSpecialChars,
  highlightTrailingWhitespace,
} from '@codemirror/view';
import {
  defaultKeymap, history, historyKeymap, indentWithTab,
} from '@codemirror/commands';
import { searchKeymap, highlightSelectionMatches } from '@codemirror/search';
import {
  HighlightStyle,
  syntaxHighlighting, indentOnInput, bracketMatching,
  foldGutter, foldKeymap, indentUnit,
} from '@codemirror/language';
import {
  autocompletion, completionKeymap,
  closeBrackets, closeBracketsKeymap,
} from '@codemirror/autocomplete';
import { python } from '@codemirror/lang-python';
import { markdown } from '@codemirror/lang-markdown';
import { yaml } from '@codemirror/lang-yaml';

import { tags } from '@lezer/highlight';

import { vim, Vim } from '@replit/codemirror-vim';
import { emacs } from '@replit/codemirror-emacs';

let anyEditorChangedFlag = false;

export function anyEditorChanged() {
  return anyEditorChangedFlag;
}

export function resetAnyEditorChanged() {
  anyEditorChangedFlag = false;
}

const myListener = new Compartment();

const rlDefaultKeymap = [
  ...closeBracketsKeymap,
  ...defaultKeymap,
  ...searchKeymap,
  ...historyKeymap,
  ...completionKeymap,
  ...foldKeymap,
  indentWithTab,
];

// Based on https://discuss.codemirror.net/t/dynamic-light-mode-dark-mode-how/4709/5
// Use a class highlight style, so we can handle things in CSS.
const highlightStyle = HighlightStyle.define([
  { tag: tags.atom, class: 'cmt-atom' },
  { tag: tags.comment, class: 'cmt-comment' },
  { tag: tags.keyword, class: 'cmt-keyword' },
  { tag: tags.literal, class: 'cmt-literal' },
  { tag: tags.number, class: 'cmt-number' },
  { tag: tags.operator, class: 'cmt-operator' },
  { tag: tags.separator, class: 'cmt-separator' },
  { tag: tags.string, class: 'cmt-string' },
]);

const defaultExtensionsBase = [
  lineNumbers(),
  history(),
  foldGutter(),
  indentOnInput(),
  drawSelection(),
  EditorState.allowMultipleSelections.of(true),
  dropCursor(),
  syntaxHighlighting(highlightStyle, { fallback: true }),
  bracketMatching(),
  closeBrackets(),
  autocompletion(),
  rectangularSelection(),
  highlightActiveLine(),
  highlightActiveLineGutter(),
  highlightSelectionMatches(),
  highlightSpecialChars(),
  highlightTrailingWhitespace(),
];

// based on https://codemirror.net/docs/migration/
export function editorFromTextArea(textarea, extensions, autofocus, additionalKeys) {
  // vim/emacs must come before other extensions
  extensions.push(
    ...defaultExtensionsBase,
    keymap.of([
      ...rlDefaultKeymap,
      ...additionalKeys,
    ]),
    EditorView.updateListener.of((viewUpdate) => {
      if (viewUpdate.docChanged) {
        anyEditorChangedFlag = true;
      }
    }),
    myListener.of(EditorView.updateListener.of(
      () => { },
    )),
  );

  if (textarea.disabled || textarea.readOnly) {
    extensions.push(
      EditorState.readOnly.of(true),
      EditorView.editable.of(false),
    );
  }

  const view = new EditorView({ doc: textarea.value, extensions });

  textarea.parentNode.insertBefore(view.dom, textarea);
  // eslint-disable-next-line no-param-reassign
  textarea.style.display = 'none';
  if (textarea.form) {
    textarea.form.addEventListener('submit', () => {
      // eslint-disable-next-line no-param-reassign
      textarea.value = view.state.doc.toString();
    });
  }
  textarea.classList.add('rl-managed-by-codemirror');

  if (autofocus) {
    document.addEventListener('DOMContentLoaded', () => {
      view.focus();
    });
  }

  return view;
}

export function setListener(view, fn) {
  view.dispatch({
    effects: myListener.reconfigure(
      EditorView.updateListener.of(fn),
    ),
  });
}

Vim.defineEx('write', 'w', () => {
  // assume we're submitting the changes, reset the change flag
  anyEditorChangedFlag = false;

  const textarea = document.querySelector('textarea.rl-managed-by-codemirror');
  if (textarea.form) {
    const { form } = textarea;

    // prefer 'submit' over 'save' on flow pages
    let submitButton = form.querySelector("input[type='submit'][name='submit']");
    if (submitButton) {
      submitButton.click();
      return;
    }

    submitButton = form.querySelector("input[type='submit']");
    if (submitButton) {
      submitButton.click();
    }
  }
});

export {
  EditorState,
  EditorView,
  indentUnit,
  vim, emacs,
  python, markdown, yaml,
};
