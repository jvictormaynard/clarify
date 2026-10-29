import { Redirect } from 'expo-router';

// Keep existing activation and settings links safe.
export default function Settings() { return <Redirect href="/(tabs)/preferences" />; }
