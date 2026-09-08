import { agentPrompt } from '../lib/site';

export function GET() {
  return new Response(`${agentPrompt}\n`, {
    headers: { 'Content-Type': 'text/plain; charset=utf-8' },
  });
}
