import { KeyboardPage, ScreenHeader } from '../../components/ui';
import { ComputerText } from '../../components/computer-text';
import { t } from '../../i18n';

export default function Actions() {
  // Keep the editor outside list headers and conditional catalog branches.
  return <KeyboardPage><ScreenHeader title={t('Ações')} /><ComputerText /></KeyboardPage>;
}
