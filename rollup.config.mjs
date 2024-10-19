import resolve from '@rollup/plugin-node-resolve';
import { brotliCompress } from 'zlib';
import { promisify } from 'util';
import commonjs from '@rollup/plugin-commonjs';
import terser from '@rollup/plugin-terser';
import styles from 'rollup-plugin-styler';
import gzipPlugin from 'rollup-plugin-gzip';
import replace from '@rollup/plugin-replace';

// `npm run build` -> `production` is true
// `npm run dev` -> `production` is false
const production = !process.env.ROLLUP_WATCH;

const brotliPromise = promisify(brotliCompress);

const defaultPlugins = [
  resolve(),
  styles(),
  commonjs(),
  production && terser(), // minify, but only in production
  production && gzipPlugin(),
  production && gzipPlugin({
    customCompression: (content) => brotliPromise(Buffer.from(content)),
    fileName: '.br',
  }),
  replace({
    values: {
      'process.env.NODE_ENV': JSON.stringify('production'),
    },
    preventAssignment: true,
  }),
];

export default [
  {
    input: 'frontend/js/base.js',
    output: {
      file: 'frontend-dist/bundle-base.js',
      format: 'iife',
      sourcemap: true,
    },
    plugins: defaultPlugins,
  },
  {
    input: 'frontend/js/base-with-markup.js',
    output: {
      file: 'frontend-dist/bundle-base-with-markup.js',
      format: 'iife',
      sourcemap: true,
    },
    plugins: defaultPlugins,
  },
  {
    input: 'frontend/js/fullcalendar.js',
    output: {
      file: 'frontend-dist/bundle-fullcalendar.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlFullCalendar',
    },
    plugins: defaultPlugins,
  },
  {
    input: 'frontend/js/datatables.js',
    output: {
      file: 'frontend-dist/bundle-datatables.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlDataTables',
      // Otherwise there are complaints about datatables trying to set attributes
      // on window.
      strict: false,
    },
    plugins: defaultPlugins,
  },
  {
    input: 'frontend/js/codemirror.js',
    output: {
      file: 'frontend-dist/bundle-codemirror.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlCodemirror',
    },
    plugins: defaultPlugins,
  },
  {
    input: 'frontend/js/prosemirror.js',
    output: {
      file: 'frontend-dist/bundle-prosemirror.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlProsemirror',
    },
    plugins: defaultPlugins,
  },
];
