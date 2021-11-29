import resolve from '@rollup/plugin-node-resolve';
import commonjs from '@rollup/plugin-commonjs';
import { terser } from 'rollup-plugin-terser';
import styles from 'rollup-plugin-styles';

// `npm run build` -> `production` is true
// `npm run dev` -> `production` is false
const production = !process.env.ROLLUP_WATCH;

const defaultPlugins = [
  resolve(),
  styles(),
  commonjs(),
  production && terser(), // minify, but only in production
];

export default [
  {
    input: 'relate/static/js/base.js',
    output: {
      file: 'frontend-dist/bundle-base.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlBase',
    },
    plugins: defaultPlugins,

  },
  {
    input: 'relate/static/js/base-with-markup.js',
    output: {
      file: 'frontend-dist/bundle-base-with-markup.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlBase',
    },
    plugins: defaultPlugins,
  },
  {
    input: 'relate/static/js/fullcalendar.js',
    output: {
      file: 'frontend-dist/bundle-fullcalendar.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlFullCalendar',
    },
    plugins: defaultPlugins,
  },
  {
    input: 'relate/static/js/datatables.js',
    output: {
      file: 'frontend-dist/bundle-datatables.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlDataTables',
    },
    plugins: defaultPlugins,
  },
];
