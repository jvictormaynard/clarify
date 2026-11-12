const { withDangerousMod, withXcodeProject } = require('expo/config-plugins');
const fs = require('node:fs');
const path = require('node:path');
const plist = require('@expo/plist').default;

// Settings owns its own presentation. These groups add instructions below its system rows.
const groups = [
  { title: 'Configurar o Clarify', detail: '1. Toque em Teclados.\n2. Ative Clarify.\n3. Ative Permitir Acesso Total e confirme Permitir.\n4. Volte ao Clarify para ativar o microfone e experimentar um ditado.' },
  { title: 'Sua privacidade', detail: 'O Acesso Total permite que o teclado envie seu ditado ao aplicativo Clarify. Áudio e texto são processados na sua conta ou no computador conectado, conforme sua escolha.' },
];
module.exports = function withClarifySettings(config) {
  config = withDangerousMod(config, ['ios', async mod => {
    const catalog = JSON.parse(fs.readFileSync(path.resolve(mod.modRequest.projectRoot, '../shared/ui_strings.json'), 'utf8'));
    const output = path.join(mod.modRequest.platformProjectRoot, 'Settings.bundle');
    fs.mkdirSync(output, { recursive: true });
    fs.writeFileSync(path.join(output, 'Root.plist'), plist.build({ StringsTable: 'Root', PreferenceSpecifiers:
      groups.map(group => ({ Type: 'PSGroupSpecifier', Title: group.title, FooterText: group.detail })) }));
    for (const locale of ['pt', 'en', 'es']) {
      const folder = path.join(output, `${locale}.lproj`);
      fs.mkdirSync(folder, { recursive: true });
      const keys = groups.flatMap(group => [group.title, group.detail]);
      fs.writeFileSync(path.join(folder, 'Root.strings'), keys.map(key => {
        const value = catalog[key]?.[locale];
        if (!value) throw new Error(`Missing Settings translation: ${locale}/${key}`);
        return `${JSON.stringify(key)} = ${JSON.stringify(value)};`;
      }).join('\n') + '\n');
    }
    return mod;
  }]);
  return withXcodeProject(config, mod => {
    const project = mod.modResults;
    const target = project.getFirstTarget().uuid;
    const group = project.getFirstProject().firstProject.mainGroup;
    // iOS discovers a settings bundle by this exact installed name.
    const file = 'Settings.bundle';
    if (!project.hasFile(file)) project.addResourceFile(file, { target }, group);
    return mod;
  });
};
