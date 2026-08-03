function otwin_conformance()
% OTWIN_CONFORMANCE  Conformance adapter for the MATLAB binding.
%
%   Reads one fixture on stdin, writes one result document on stdout.
%   Reports NUMBERS ONLY and never judges itself — all judgement happens in
%   otwin-spec, so a bug in MATLAB cannot hide a bug in MATLAB's models.
%
%     otwin-conformance "matlab -batch otwin_conformance" --name matlab
%
%   Fill in BUILDMODEL against the +otwin package. Anything not yet
%   implemented should be added to `unsupported` — a declared gap is honest
%   and does not block conformance; a wrong answer does.

    fx = jsondecode(fileread('/dev/stdin'));
    res = struct('fixture_id', fx.id, 'implementation', 'matlab', ...
                 'version', '0.1.0', 'unsupported', {{}}, 'outputs', struct());
    try
        res.outputs = runFixture(fx);
    catch err
        res.unsupported = {fx.id};
        res.note = err.message;
    end
    fprintf('%s', jsonencode(res));
end

function out = runFixture(fx)
    % Fields beginning with '_' are documentation (units, notes), not parameters.
    p = fx.parameters;
    f = fieldnames(p);
    p = rmfield(p, f(startsWith(f, '_')));
    m  = buildModel(fx.model_kind, p);
    sc = fx.scenario;
    out = struct();
    if isfield(sc, 'sample_states')
        S = num2cell(sc.sample_states, 2);
        out.matrices.J = cellfun(@(x) m.J(x(:)), S, 'UniformOutput', false);
        out.matrices.R = cellfun(@(x) m.R(x(:)), S, 'UniformOutput', false);
        out.energy     = cellfun(@(x) m.H(x(:)), S);
    end
    if isfield(sc, 'x0')
        t = linspace(sc.t.start, sc.t.stop, sc.t.num);
        if isfield(sc, 'u') && strcmp(sc.u.kind, 'constant')
            U = repmat(sc.u.value(:)', numel(t), 1);
        else
            U = zeros(numel(t), m.n_inputs);
        end
        [X, E] = simulateRK4(m, sc.x0(:), t, U);
        out.t = t;  out.state = X;  out.energy = E;
    end
end

function m = buildModel(kind, p)
    switch kind
        case 'dc_motor'
            L = p.L; Jm = p.inertia; Re = p.Re; b = p.b; K = p.K;
            m.H      = @(x) 0.5*x(1)^2/L + 0.5*x(2)^2/Jm;
            m.grad_H = @(x) [x(1)/L; x(2)/Jm];
            m.J      = @(x) [0 -K; K 0];
            m.R      = @(x) [Re 0; 0 b];
            m.g      = @(x) [1; 0];
            m.n_states = 2; m.n_inputs = 1;
        otherwise
            error('otwin:notImplemented', 'model_kind %s not implemented', kind);
    end
end

function [X, E] = simulateRK4(m, x0, t, U)
    n = numel(t);  X = zeros(n, m.n_states);  X(1,:) = x0';
    f = @(x,u) (m.J(x) - m.R(x)) * m.grad_H(x) + m.g(x) * u;
    for i = 1:n-1
        dt = t(i+1) - t(i);  x = X(i,:)';  u = U(i,:)';
        k1 = f(x,u);  k2 = f(x + 0.5*dt*k1, u);
        k3 = f(x + 0.5*dt*k2, u);  k4 = f(x + dt*k3, u);
        X(i+1,:) = (x + (dt/6)*(k1 + 2*k2 + 2*k3 + k4))';
    end
    E = arrayfun(@(i) m.H(X(i,:)'), 1:n)';
end
