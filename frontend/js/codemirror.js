import {
  autocompletion,
  closeBrackets,
  closeBracketsKeymap,
  completionKeymap,
} from '@codemirror/autocomplete';
import {
  defaultKeymap,
  history,
  historyKeymap,
  indentWithTab,
} from '@codemirror/commands';
import { markdown } from '@codemirror/lang-markdown';
import { python } from '@codemirror/lang-python';
import {
  bracketMatching,
  foldGutter,
  foldKeymap,
  HighlightStyle,
  indentOnInput,
  indentUnit,
  StreamLanguage,
  syntaxHighlighting,
} from '@codemirror/language';
import { yaml as yamlStreamParser } from '@codemirror/legacy-modes/mode/yaml';
import { highlightSelectionMatches, searchKeymap } from '@codemirror/search';
import { Compartment, EditorState } from '@codemirror/state';
import {
  drawSelection,
  dropCursor,
  EditorView,
  highlightActiveLine,
  highlightActiveLineGutter,
  highlightSpecialChars,
  highlightTrailingWhitespace,
  keymap,
  lineNumbers,
  rectangularSelection,
} from '@codemirror/view';

import { tags } from '@lezer/highlight';
import { emacs } from '@replit/codemirror-emacs';
import { Vim, vim } from '@replit/codemirror-vim';

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

const yaml = () => StreamLanguage.define(yamlStreamParser);

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
export function editorFromTextArea(
  textarea,
  extensions,
  autofocus,
  additionalKeys,
) {
  // vim/emacs must come before other extensions
  extensions.push(
    ...defaultExtensionsBase,
    keymap.of([...rlDefaultKeymap, ...additionalKeys]),
    EditorView.updateListener.of((viewUpdate) => {
      if (viewUpdate.docChanged) {
        anyEditorChangedFlag = true;
      }
    }),
    // biome-ignore lint/suspicious/noEmptyBlockStatements: placeholder listener required by CodeMirror API
    myListener.of(EditorView.updateListener.of(() => {})),
  );

  if (textarea.disabled || textarea.readOnly) {
    extensions.push(
      EditorState.readOnly.of(true),
      EditorView.editable.of(false),
    );
  }

  const view = new EditorView({ doc: textarea.value, extensions });

  textarea.parentNode.insertBefore(view.dom, textarea);
  textarea.style.display = 'none';
  if (textarea.form) {
    textarea.form.addEventListener('submit', () => {
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
    effects: myListener.reconfigure(EditorView.updateListener.of(fn)),
  });
}

Vim.defineEx('write', 'w', (cm) => {
  const form = cm.cm6.dom.closest('form');
  if (form) {
    // prefer 'submit' over 'save' on flow pages
    let submitButton = form.querySelector(
      "input[type='submit'][name='submit']",
    );
    if (submitButton) {
      anyEditorChangedFlag = false;
      submitButton.click();
      return;
    }

    submitButton = form.querySelector("input[type='submit']");
    if (submitButton) {
      anyEditorChangedFlag = false;
      submitButton.click();
    }
  }
});

export {
  EditorState,
  EditorView,
  emacs,
  indentUnit,
  markdown,
  python,
  vim,
  yaml,
};
