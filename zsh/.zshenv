# Toolchain/PATH setup lives in .zprofile, not here. .zshenv runs for every zsh
# invocation, so evaluating fnm here ran it a second time per login shell and
# stacked a duplicate multishell dir onto PATH.
