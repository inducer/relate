import 'katex/dist/katex.min.css';

// prosemirror imports
import { Schema, Node } from 'prosemirror-model';
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

import {
  mathPlugin, mathBackspaceCmd, insertMathCmd, mathSerializer,
  makeBlockMathInputRule, makeInlineMathInputRule,
  REGEX_INLINE_MATH_DOLLARS, REGEX_BLOCK_MATH_DOLLARS,
// I've no idea why eslint can't find the module; rollup can.
// eslint-disable-next-line import/no-unresolved
} from '@benrbray/prosemirror-math';
import '@benrbray/prosemirror-math/dist/prosemirror-math.css';

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

// eslint-disable-next-line import/prefer-default-export
export function editorFromTextArea(textarea, autofocus) {
  const plugins = [
    ...exampleSetup({ schema }),
    mathPlugin,
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
