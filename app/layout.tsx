import type { Metadata } from 'next';
import './globals.css';
export const metadata: Metadata = { title:'Academian | Agent Workbench', description:'Design, review and run education workflows with governed knowledge.' };
export default function Layout({children}:{children:React.ReactNode}) { return <html lang="en"><body>{children}</body></html>; }
