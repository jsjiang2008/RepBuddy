import js from '@eslint/js'
import globals from 'globals'
import reactHooks from 'eslint-plugin-react-hooks'
import reactRefresh from 'eslint-plugin-react-refresh'
import tseslint from 'typescript-eslint'
import { defineConfig, globalIgnores } from 'eslint/config'

// ESLint checks source files for common JavaScript, TypeScript, and React mistakes.
export default defineConfig([
  // Generated build files do not need source code checks.
  globalIgnores(['dist']),
  {
    files: ['**/*.{ts,tsx}'],
    // Reuse the recommended rules, including correct use of React hooks.
    extends: [
      js.configs.recommended,
      tseslint.configs.recommended,
      reactHooks.configs.flat.recommended,
      reactRefresh.configs.vite,
    ],
    // Browser globals include document, window, and other built in page tools.
    languageOptions: {
      globals: globals.browser,
    },
  },
])
