/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {
      backgroundImage: {
        'wood-pattern': "linear-gradient(rgba(139, 69, 19, 0.15), rgba(139, 69, 19, 0.15)), url('https://www.transparenttextures.com/patterns/wooden-planks.png')",
      },
      fontFamily: {
        heading: ['Fredoka', 'sans-serif'],
        sans: ['Nunito', 'sans-serif'],
        serif: ['Libre Baskerville', 'serif'],
      },
    },
  },
  plugins: [],
}
