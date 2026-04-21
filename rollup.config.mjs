import commonjs from '@rollup/plugin-commonjs';
import resolve from '@rollup/plugin-node-resolve';
import replace from '@rollup/plugin-replace';
import terser from '@rollup/plugin-terser';
import gzipPlugin from 'rollup-plugin-gzip';
import styles from 'rollup-plugin-styler';
import { promisify } from 'util';
import { brotliCompress } from 'zlib';

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
  production &&
    gzipPlugin({
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

const bundles = {
  base: {
    input: 'frontend/js/base.js',
    output: {
      file: 'frontend-dist/bundle-base.js',
      format: 'iife',
      sourcemap: true,
    },
  },
  'base-with-markup': {
    input: 'frontend/js/base-with-markup.js',
    output: {
      file: 'frontend-dist/bundle-base-with-markup.js',
      format: 'iife',
      sourcemap: true,
    },
  },
  fullcalendar: {
    input: 'frontend/js/fullcalendar.js',
    output: {
      file: 'frontend-dist/bundle-fullcalendar.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlFullCalendar',
    },
  },
  datatables: {
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
  },
  codemirror: {
    input: 'frontend/js/codemirror.js',
    output: {
      file: 'frontend-dist/bundle-codemirror.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlCodemirror',
    },
  },
  prosemirror: {
    input: 'frontend/js/prosemirror.js',
    output: {
      file: 'frontend-dist/bundle-prosemirror.js',
      format: 'iife',
      sourcemap: true,
      name: 'rlProsemirror',
    },
  },
  analytics: {
    input: 'frontend/js/analytics.js',
    output: {
      // "analytics" as a file name is commonly blocked (e.g. by uBlock)
      file: 'frontend-dist/bundle-analysis.js',
      format: 'iife',
      sourcemap: true,
    },
    plugins: defaultPlugins,
  },
};

export default function (commandLineArgs) {
  const { configBundle } = commandLineArgs;

  if (configBundle) {
    if (!(configBundle in bundles)) {
      throw new Error(
        `Unknown bundle: ${configBundle}. Available: ${Object.keys(bundles).join(', ')}`,
      );
    }
    return [{ ...bundles[configBundle], plugins: defaultPlugins }];
  }

  return Object.values(bundles).map((bundle) => ({
    ...bundle,
    plugins: defaultPlugins,
  }));
}
