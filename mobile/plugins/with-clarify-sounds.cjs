const { withDangerousMod, withXcodeProject } = require('expo/config-plugins');
const fs = require('node:fs');
const path = require('node:path');
const sounds = ['dictation-start.wav', 'dictation-stop.wav'];

module.exports = function withClarifySounds(config) {
  config = withDangerousMod(config, ['ios', async (mod) => {
    const source = path.resolve(mod.modRequest.projectRoot, '../assets/sounds');
    const output = path.join(mod.modRequest.platformProjectRoot, 'ClarifySounds');
    fs.mkdirSync(output, { recursive: true });
    for (const name of sounds) fs.copyFileSync(path.join(source, name), path.join(output, name));
    return mod;
  }]);
  return withXcodeProject(config, (mod) => {
    const project = mod.modResults;
    const target = project.getFirstTarget().uuid;
    const group = project.getFirstProject().firstProject.mainGroup;
    for (const name of sounds) {
      const file = `ClarifySounds/${name}`;
      if (!project.hasFile(file)) project.addResourceFile(file, { target }, group);
    }
    return mod;
  });
};
