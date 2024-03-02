import { EditorState } from '@codemirror/state';
import {
  EditorView, keymap, lineNumbers, highlightActiveLine,
} from '@codemirror/view';
import { defaultKeymap, history, historyKeymap, indentWithTab } from '@codemirror/commands';
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

import { tags } from '@lezer/highlight';

import { vim } from "@replit/codemirror-vim";
import { emacs } from "@replit/codemirror-emacs";

// from https://codemirror.net/docs/migration/
function editorFromTextArea(textarea, extensions) {
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
  return view;
}

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

export {
  EditorState,
  EditorView, keymap, lineNumbers, highlightActiveLine,
  defaultKeymap, history, historyKeymap, indentWithTab,
  searchKeymap, highlightSelectionMatches,
  highlightStyle, syntaxHighlighting, indentOnInput, bracketMatching,
  foldGutter, foldKeymap, indentUnit,
  autocompletion, completionKeymap, closeBrackets, closeBracketsKeymap,
  python, markdown,
  vim, emacs,
  editorFromTextArea,
};
