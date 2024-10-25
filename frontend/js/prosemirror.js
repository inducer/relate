// Copyright (C) 2017 University of Illinois Board of Trustees
// Copyright (C) 2024 Marijn Haverbeke

// Contains parts of
// https://github.com/ProseMirror/prosemirror-markdown/blob/99b6f0a6c377a2c010320f4fdd883e4868aaf122/src/from_markdown.ts
// Used under the MIT license.

// Permission is hereby granted, free of charge, to any person obtaining a copy
// of this software and associated documentation files (the "Software"), to deal
// in the Software without restriction, including without limitation the rights
// to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
// copies of the Software, and to permit persons to whom the Software is
// furnished to do so, subject to the following conditions:

// The above copyright notice and this permission notice shall be included in
// all copies or substantial portions of the Software.

// THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
// IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
// FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
// AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
// LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
// OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
// THE SOFTWARE.

import 'katex/dist/katex.min.css';

// prosemirror imports
import { Schema, Node, Slice } from 'prosemirror-model';
import { EditorView } from 'prosemirror-view';
import { EditorState, Plugin, PluginKey } from 'prosemirror-state';
import { schema as basicSchema } from 'prosemirror-schema-basic';
import { addListNodes } from 'prosemirror-schema-list';
import {
  chainCommands, deleteSelection, selectNodeBackward, joinBackward,
} from 'prosemirror-commands';
import { keymap } from 'prosemirror-keymap';
import { inputRules } from 'prosemirror-inputrules';
import 'prosemirror-view/style/prosemirror.css';
import 'prosemirror-menu/style/menu.css';

import { exampleSetup } from 'prosemirror-example-setup';
import 'prosemirror-example-setup/style/style.css';

import { MarkdownParser } from 'prosemirror-markdown';
import MarkdownIt from 'markdown-it';
import markdownItMath from '@vscode/markdown-it-katex';

import {
  mathPlugin, mathBackspaceCmd, insertMathCmd, mathSerializer,
  makeBlockMathInputRule, makeInlineMathInputRule,
  REGEX_INLINE_MATH_DOLLARS, REGEX_BLOCK_MATH_DOLLARS,
// I've no idea why eslint can't find the module; rollup can.
// eslint-disable-next-line import/no-unresolved
} from '@benrbray/prosemirror-math';
import '@benrbray/prosemirror-math/dist/prosemirror-math.css';

let anyEditorChangedFlag = false;

export function anyEditorChanged() {
  return anyEditorChangedFlag;
}

export function resetAnyEditorChanged() {
  anyEditorChangedFlag = false;
}

const schema = new Schema({
  nodes: addListNodes(basicSchema.spec.nodes, 'paragraph block*', 'block')
    .remove('image')
    .addToEnd('math_inline', {
      group: 'inline math',
      content: 'text*', // important!
      inline: true, // important!
      atom: true, // important!
      toDOM: () => ['math-inline', { class: 'math-node' }, 0],
      parseDOM: [{
        tag: 'math-inline', // important!
      }],
    })
    .addToEnd('math_display', {
      group: 'block math',
      content: 'text*', // important!
      atom: true, // important!
      code: true, // important!
      toDOM: () => ['math-display', { class: 'math-node' }, 0],
      parseDOM: [{
        tag: 'math-display', // important!
      }],
    }),
  marks: basicSchema.spec.marks,
});

const inlineMathInputRule = makeInlineMathInputRule(
  REGEX_INLINE_MATH_DOLLARS,
  schema.nodes.math_inline,
);
const blockMathInputRule = makeBlockMathInputRule(
  REGEX_BLOCK_MATH_DOLLARS,
  schema.nodes.math_display,
);

const readonlyPlugin = new Plugin({
  key: new PluginKey('readonly'),
  // Allow selections but prevent any other changes
  filterTransaction: (transaction) => transaction.docChanged === false,
});

const changeListenerPlugin = new Plugin({
  key: new PluginKey('readonly'),
  filterTransaction: (transaction) => {
    if (transaction.docChanged) {
      anyEditorChangedFlag = true;
    }
    return true;
  },
});

// {{{ handle markdown paste

function listIsTight(tokens, i) {
  // eslint-disable-next-line no-plusplus, no-param-reassign
  while (++i < tokens.length) {
    if (tokens[i].type !== 'list_item_open') return tokens[i].hidden;
  }
  return false;
}

function markdownToProsemirrorParser() {
  const mdit = MarkdownIt('commonmark', { html: false }).use(markdownItMath, {
    enableBareBlocks: true,
  });
  return new MarkdownParser(schema, mdit, {
    blockquote: { block: 'blockquote' },
    paragraph: { block: 'paragraph' },
    list_item: { block: 'list_item' },
    bullet_list: {
      block: 'bullet_list',
      getAttrs: (_, tokens, i) => ({ tight: listIsTight(tokens, i) }),
    },
    ordered_list: {
      block: 'ordered_list',
      getAttrs: (tok, tokens, i) => ({
        order: +tok.attrGet('start') || 1,
        tight: listIsTight(tokens, i),
      }),
    },
    heading: {
      block: 'heading',
      getAttrs: (tok) => ({ level: +tok.tag.slice(1) }),
    },
    code_block: { block: 'code_block', noCloseToken: true },
    fence: {
      block: 'code_block',
      getAttrs: (tok) => ({ params: tok.info || '' }),
      noCloseToken: true,
    },
    hr: { node: 'horizontal_rule' },
    hardbreak: { node: 'hard_break' },

    em: { mark: 'em' },
    strong: { mark: 'strong' },
    link: {
      mark: 'link',
      getAttrs: (tok) => ({
        href: tok.attrGet('href'),
        title: tok.attrGet('title') || null,
      }),
    },
    code_inline: { mark: 'code', noCloseToken: true },

    math_inline: { block: 'math_inline', noCloseToken: true },
    math_block: { block: 'math_display', noCloseToken: true },
  });
}

const pasteMarkdownPlugin = new Plugin({
  props: {
    handlePaste(view, event/* , slice */) {
      const clipboardText = event.clipboardData.getData('text/plain');
      if (!clipboardText) return false;

      const doc = markdownToProsemirrorParser().parse(clipboardText);
      const transaction = view.state.tr.replaceSelection(new Slice(doc.content, 0, 0));
      view.dispatch(transaction);

      return true;
    },
  },
});

// }}}

// eslint-disable-next-line import/prefer-default-export
export function editorFromTextArea(textarea, autofocus) {
  const plugins = [
    ...exampleSetup({ schema }),
    mathPlugin,
    pasteMarkdownPlugin,
    keymap({
      'Mod-Space': insertMathCmd(schema.nodes.math_inline),

      Backspace: chainCommands(
        deleteSelection,
        mathBackspaceCmd,
        joinBackward,
        selectNodeBackward,
      ),
    }),
    inputRules({ rules: [inlineMathInputRule, blockMathInputRule] }),
  ];

  if (textarea.disabled || textarea.readOnly) {
    plugins.push(readonlyPlugin);
  }
  // Change listener should be after readonly.
  plugins.push(changeListenerPlugin);

  let docJson = null;
  if (textarea.value) {
    docJson = JSON.parse(textarea.value);
  }

  let doc;
  if (docJson) {
    doc = Node.fromJSON(schema, docJson);
  } else {
    doc = schema.topNodeType.createAndFill();
  }

  const state = EditorState.create({ schema, plugins, doc });

  const editorElt = document.createElement('div');
  editorElt.classList.add('rl-prosemirror-container');
  const view = new EditorView(editorElt, {
    state,
    clipboardTextSerializer: mathSerializer.serializeSlice,
  });

  if (autofocus) {
    document.addEventListener('DOMContentLoaded', () => {
      view.focus();
    });
  }

  textarea.parentNode.insertBefore(editorElt, textarea);

  // eslint-disable-next-line no-param-reassign
  textarea.style.display = 'none';
  if (textarea.form) {
    textarea.form.addEventListener('submit', () => {
      // eslint-disable-next-line no-param-reassign
      textarea.value = JSON.stringify(view.state.doc.toJSON());
    });
  }
  textarea.classList.add('rl-managed-by-prosemirror');

  return view;
}
