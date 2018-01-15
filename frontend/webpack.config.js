const path = require('path');
const webpack = require('webpack');

const config = {
  entry: './entrypoints/default.js',
  output: {
    filename: 'default.js',
    path: path.resolve(__dirname, 'dist')
  },
   module: {
     rules: [
       {
         test: /(\.ttf|\.woff2?|\.eot|\.svg|\.png|\.gif)$/,
         use: [
           'file-loader'
         ]
       },
       {
         test: /\.css$/,
         use: [
           'style-loader',
           'css-loader'
         ]
       }
     ]
   }
  , plugins: [ new webpack.optimize.UglifyJsPlugin({minimize: true}) ]
};

module.exports = config;
