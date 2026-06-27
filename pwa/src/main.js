import { mount } from 'svelte';
import './app.css';
import App from './App.svelte';
import { loadAppearance, applyAppearance } from './lib/theme.js';

// Apply the saved theme/accent before the first paint to avoid a flash.
applyAppearance(loadAppearance());

export default mount(App, { target: document.getElementById('app') });
