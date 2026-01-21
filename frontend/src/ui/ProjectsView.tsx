import React, { useState, useEffect, useRef } from 'react';
import {
  FolderKanban,
  Plus,
  BookOpen,
  Briefcase,
  StickyNote,
  Apple,
  X,
  UploadCloud,
  FileText,
  Sparkles,
  ChevronRight,
  Settings,
  Image as ImageIcon,
  Search,
  ArrowRight,
  MessageSquare,
  Film
} from 'lucide-react';

// --- Components ---

const ProjectCard = ({ icon: Icon, iconColor, title, type, description, onClick }: {
  icon: React.ElementType
  iconColor: string
  title: string
  type: string
  description: string
  onClick: () => void
}) => (
  <div
    onClick={onClick}
    className="flex flex-col gap-3 p-4 rounded-2xl bg-[#2b2d31] hover:bg-[#32343a] transition-colors cursor-pointer group border border-transparent hover:border-[#3f4148]"
  >
    <div className="flex justify-between items-start">
      <div className="flex items-center gap-3">
        <Icon size={20} className={iconColor} strokeWidth={2.5} />
        <h3 className="font-semibold text-sm text-gray-100">{title}</h3>
      </div>
      {type && (
        <span className="text-xs font-semibold text-gray-500 uppercase tracking-wide">
          {type}
        </span>
      )}
    </div>
    <p className="text-xs text-gray-400 leading-relaxed line-clamp-2">
      {description}
    </p>
  </div>
);

const TabButton = ({ active, label, onClick }: {
  active: boolean
  label: string
  onClick: () => void
}) => (
  <button
    onClick={onClick}
    className={`px-3 py-2 text-sm font-medium border-b-2 transition-colors ${
      active
        ? 'border-white text-white'
        : 'border-transparent text-gray-400 hover:text-gray-200 hover:border-gray-700'
    }`}
  >
    {label}
  </button>
);

const FileUploadItem = ({ name, size, onRemove }: {
  name: string
  size: string
  onRemove?: () => void
}) => (
  <div className="flex items-center justify-between p-2 rounded-lg bg-[#1e1f22] border border-[#383a40] group">
    <div className="flex items-center gap-3">
      <div className="p-1.5 bg-[#2b2d31] rounded-md text-blue-400">
        <FileText size={16} />
      </div>
      <div className="flex flex-col">
        <span className="text-sm text-gray-200 truncate max-w-[150px]">{name}</span>
        <span className="text-xs text-gray-500">{size}</span>
      </div>
    </div>
    {onRemove && (
      <button
        onClick={onRemove}
        className="p-1 text-gray-500 hover:text-red-400 opacity-0 group-hover:opacity-100 transition-opacity"
      >
        <X size={16} />
      </button>
    )}
  </div>
);

const ProjectWizard = ({ onClose, onSave }: {
  onClose: () => void
  onSave: (data: any) => void
}) => {
  const [step, setStep] = useState(1);
  const [files, setFiles] = useState<Array<{name: string, size: string, file?: File}>>([]);
  const [projectName, setProjectName] = useState('');
  const [description, setDescription] = useState('');
  const [instructions, setInstructions] = useState('');
  const [isPublic, setIsPublic] = useState(false);
  const [projectType, setProjectType] = useState<'chat' | 'image' | 'video'>('chat');
  const fileInputRef = useRef<HTMLInputElement>(null);

  // Mock file upload handler
  const handleDrop = (e: React.DragEvent) => {
    e.preventDefault();
    const droppedFiles = Array.from(e.dataTransfer.files);
    const newFiles = droppedFiles.map(f => ({
      name: f.name,
      size: `${(f.size / 1024 / 1024).toFixed(2)} MB`,
      file: f
    }));
    setFiles([...files, ...newFiles]);
  };

  const handleFileSelect = (e: React.ChangeEvent<HTMLInputElement>) => {
    if (e.target.files) {
      const selectedFiles = Array.from(e.target.files);
      const newFiles = selectedFiles.map(f => ({
        name: f.name,
        size: `${(f.size / 1024 / 1024).toFixed(2)} MB`,
        file: f
      }));
      setFiles([...files, ...newFiles]);
    }
  };

  const handleCreate = () => {
    const projectData = {
      name: projectName || 'Untitled Project',
      description,
      instructions,
      files: files,
      is_public: isPublic,
      project_type: projectType
    };
    onSave(projectData);
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200">
      <div
        className="w-full max-w-2xl bg-[#1e1f22] rounded-2xl border border-[#383a40] shadow-2xl flex flex-col max-h-[90vh] overflow-hidden"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-center justify-between px-6 py-4 border-b border-[#2b2d31]">
          <div>
            <h2 className="text-lg font-semibold text-white">Create new project</h2>
            <p className="text-xs text-gray-400">Step {step} of 2</p>
          </div>
          <button
            onClick={onClose}
            className="p-2 text-gray-400 hover:text-white hover:bg-[#2b2d31] rounded-lg transition-colors"
          >
            <X size={20} />
          </button>
        </div>

        {/* Content */}
        <div className="flex-1 overflow-y-auto p-6 custom-scrollbar">
          {step === 1 ? (
            <div className="space-y-6">
              {/* Project Type Selection */}
              <div className="space-y-2">
                <label className="block text-sm font-medium text-gray-300 flex items-center gap-2">
                  <Sparkles size={14} className="text-blue-400" />
                  Project Type
                </label>
                <div className="grid grid-cols-3 gap-3">
                  <button
                    type="button"
                    onClick={() => setProjectType('chat')}
                    className={`p-4 rounded-xl border-2 transition-all ${
                      projectType === 'chat'
                        ? 'border-blue-500 bg-blue-500/10'
                        : 'border-[#383a40] bg-[#2b2d31] hover:border-[#4f5158]'
                    }`}
                  >
                    <MessageSquare size={24} className={`mx-auto mb-2 ${projectType === 'chat' ? 'text-blue-400' : 'text-gray-400'}`} />
                    <div className="text-sm font-medium text-gray-200">Chat / LLM</div>
                    <div className="text-xs text-gray-500 mt-1">Custom AI assistant</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setProjectType('image')}
                    className={`p-4 rounded-xl border-2 transition-all ${
                      projectType === 'image'
                        ? 'border-purple-500 bg-purple-500/10'
                        : 'border-[#383a40] bg-[#2b2d31] hover:border-[#4f5158]'
                    }`}
                  >
                    <ImageIcon size={24} className={`mx-auto mb-2 ${projectType === 'image' ? 'text-purple-400' : 'text-gray-400'}`} />
                    <div className="text-sm font-medium text-gray-200">Image</div>
                    <div className="text-xs text-gray-500 mt-1">Image generation</div>
                  </button>
                  <button
                    type="button"
                    onClick={() => setProjectType('video')}
                    className={`p-4 rounded-xl border-2 transition-all ${
                      projectType === 'video'
                        ? 'border-green-500 bg-green-500/10'
                        : 'border-[#383a40] bg-[#2b2d31] hover:border-[#4f5158]'
                    }`}
                  >
                    <Film size={24} className={`mx-auto mb-2 ${projectType === 'video' ? 'text-green-400' : 'text-gray-400'}`} />
                    <div className="text-sm font-medium text-gray-200">Video</div>
                    <div className="text-xs text-gray-500 mt-1">Video generation</div>
                  </button>
                </div>
              </div>

              {/* Project Icon & Name */}
              <div className="space-y-4">
                <label className="block text-sm font-medium text-gray-300">Project Identity</label>
                <div className="flex gap-4">
                  <button className="shrink-0 w-16 h-16 rounded-xl bg-[#2b2d31] border border-[#383a40] border-dashed hover:border-blue-500 hover:text-blue-500 flex items-center justify-center text-gray-500 transition-colors">
                    <ImageIcon size={24} />
                  </button>
                  <div className="flex-1 space-y-3">
                    <input
                      type="text"
                      placeholder="Project Name"
                      value={projectName}
                      onChange={(e) => setProjectName(e.target.value)}
                      className="w-full bg-[#2b2d31] border border-[#383a40] rounded-xl px-4 py-2.5 text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all"
                    />
                    <input
                      type="text"
                      placeholder="Short description (optional)"
                      value={description}
                      onChange={(e) => setDescription(e.target.value)}
                      className="w-full bg-[#2b2d31] border border-[#383a40] rounded-xl px-4 py-2.5 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all"
                    />
                  </div>
                </div>
              </div>

              {/* Custom Instructions */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium text-gray-300 flex items-center gap-2">
                    <Sparkles size={14} className="text-blue-400" />
                    Custom Instructions
                  </label>
                  <span className="text-xs text-gray-500">How should HomePilot behave?</span>
                </div>
                <textarea
                  value={instructions}
                  onChange={(e) => setInstructions(e.target.value)}
                  className="w-full h-32 bg-[#2b2d31] border border-[#383a40] rounded-xl p-4 text-sm text-white placeholder-gray-500 focus:outline-none focus:border-blue-500 focus:ring-1 focus:ring-blue-500 transition-all resize-none"
                  placeholder={
                    projectType === 'chat'
                      ? "E.g., You are an expert Python developer. Always prefer functional programming patterns..."
                      : projectType === 'image'
                      ? "E.g., Generate images in a cyberpunk art style with neon colors..."
                      : "E.g., Create cinematic videos with smooth camera movements..."
                  }
                />
              </div>
            </div>
          ) : (
            <div className="space-y-6">
              {/* Knowledge Base */}
              <div className="space-y-2">
                <div className="flex items-center justify-between">
                  <label className="text-sm font-medium text-gray-300">Knowledge Base</label>
                  <span className="text-xs text-gray-500">PDF, TXT, MD supported</span>
                </div>

                <div
                  className="w-full h-32 border-2 border-dashed border-[#383a40] rounded-xl bg-[#2b2d31]/50 flex flex-col items-center justify-center gap-2 cursor-pointer hover:border-blue-500/50 hover:bg-[#2b2d31] transition-all"
                  onClick={() => fileInputRef.current?.click()}
                  onDrop={handleDrop}
                  onDragOver={(e) => e.preventDefault()}
                >
                  <div className="p-3 bg-[#1e1f22] rounded-full text-gray-400">
                    <UploadCloud size={24} />
                  </div>
                  <p className="text-sm text-gray-400">Click to upload or drag & drop</p>
                </div>

                <input
                  ref={fileInputRef}
                  type="file"
                  multiple
                  accept=".pdf,.txt,.md"
                  onChange={handleFileSelect}
                  className="hidden"
                />

                {/* File List */}
                {files.length > 0 && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-2 mt-4">
                    {files.map((f, i) => (
                      <FileUploadItem
                        key={i}
                        name={f.name}
                        size={f.size}
                        onRemove={() => setFiles(files.filter((_, idx) => idx !== i))}
                      />
                    ))}
                  </div>
                )}
              </div>

              {/* Settings Toggles */}
              <div className="space-y-3 pt-4 border-t border-[#2b2d31]">
                <label className="text-sm font-medium text-gray-300 mb-2 block">Settings</label>
                <div className="flex items-center justify-between p-3 rounded-xl bg-[#2b2d31]">
                  <span className="text-sm text-gray-300">Make project public</span>
                  <button
                    onClick={() => setIsPublic(!isPublic)}
                    className={`w-10 h-5 rounded-full relative transition-colors ${
                      isPublic ? 'bg-blue-600' : 'bg-[#383a40]'
                    }`}
                  >
                    <div
                      className={`absolute top-1 w-3 h-3 bg-white rounded-full transition-all ${
                        isPublic ? 'left-6' : 'left-1'
                      }`}
                    ></div>
                  </button>
                </div>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-6 border-t border-[#2b2d31] bg-[#1e1f22] flex justify-end gap-3">
          {step === 2 && (
            <button
              onClick={() => setStep(1)}
              className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition-colors"
            >
              Back
            </button>
          )}
          <button
            onClick={onClose}
            className="px-4 py-2 text-sm font-medium text-gray-300 hover:text-white transition-colors"
          >
            Cancel
          </button>
          <button
            onClick={() => step === 1 ? setStep(2) : handleCreate()}
            className="px-6 py-2 bg-white text-black text-sm font-semibold rounded-xl hover:bg-gray-200 transition-colors flex items-center gap-2"
          >
            {step === 1 ? (
              <>Next <ChevronRight size={16} /></>
            ) : (
              'Create Project'
            )}
          </button>
        </div>
      </div>
    </div>
  );
};

// --- Search Modal Component ---
const SearchModal = ({ onClose, projects, exampleProjects, onSelectProject, onCreateFromExample }: {
  onClose: () => void
  projects: any[]
  exampleProjects: any[]
  onSelectProject?: (projectId: string) => void
  onCreateFromExample?: (exampleId: string) => void
}) => {
  const [query, setQuery] = useState("");
  const inputRef = useRef<HTMLInputElement>(null);

  // Map icon names to components
  const iconMap: Record<string, React.ElementType> = {
    BookOpen,
    Briefcase,
    StickyNote,
    Apple,
    FolderKanban
  };

  // Focus input on mount
  React.useEffect(() => {
    inputRef.current?.focus();

    // Close on Escape
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handleKeyDown);
    return () => window.removeEventListener('keydown', handleKeyDown);
  }, [onClose]);

  // Combine projects and examples for search
  const allItems = [
    ...projects.map(p => ({ ...p, type: 'project', icon: 'FolderKanban', icon_color: 'text-blue-400' })),
    ...exampleProjects.map(e => ({ ...e, type: 'example' }))
  ];

  // Filter logic
  const filteredItems = query
    ? allItems.filter(item =>
        item.name.toLowerCase().includes(query.toLowerCase()) ||
        item.description?.toLowerCase().includes(query.toLowerCase())
      )
    : allItems;

  const handleItemClick = (item: any) => {
    if (item.type === 'example' && onCreateFromExample) {
      onCreateFromExample(item.id);
    } else if (item.type === 'project' && onSelectProject) {
      onSelectProject(item.id);
    }
    onClose();
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-start justify-center pt-[15vh] px-4 bg-black/60 backdrop-blur-sm animate-in fade-in duration-200"
      onClick={onClose}
    >
      <div
        className="w-full max-w-xl bg-[#1e1f22] rounded-2xl border border-[#383a40] shadow-2xl flex flex-col overflow-hidden animate-in zoom-in-95 duration-200"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Search Input Header */}
        <div className="flex items-center gap-3 px-4 py-4 border-b border-[#2b2d31]">
          <Search size={20} className="text-gray-400" />
          <input
            ref={inputRef}
            type="text"
            placeholder="Search projects..."
            className="flex-1 bg-transparent text-lg text-white placeholder-gray-500 focus:outline-none"
            value={query}
            onChange={(e) => setQuery(e.target.value)}
          />
          <button
            onClick={onClose}
            className="p-1 text-gray-500 hover:text-white bg-[#2b2d31] rounded-md text-xs font-medium px-2 py-1 transition-colors"
          >
            ESC
          </button>
        </div>

        {/* Results List */}
        <div className="max-h-[60vh] overflow-y-auto custom-scrollbar p-2">
          {filteredItems.length > 0 ? (
            <div className="space-y-1">
              {query && <div className="px-3 py-2 text-xs font-semibold text-gray-500 uppercase">Results ({filteredItems.length})</div>}
              {filteredItems.map((item) => {
                const IconComponent = iconMap[item.icon] || FolderKanban;
                return (
                  <div
                    key={item.id}
                    className="group flex items-center gap-4 p-3 rounded-xl hover:bg-[#2b2d31] cursor-pointer transition-colors"
                    onClick={() => handleItemClick(item)}
                  >
                    <div className={`p-2 rounded-lg bg-[#2b2d31] group-hover:bg-[#383a40] transition-colors ${item.icon_color || 'text-blue-400'}`}>
                      <IconComponent size={20} />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="flex items-center gap-2">
                        <h4 className="text-sm font-medium text-gray-200 group-hover:text-white truncate">
                          {item.name}
                        </h4>
                        {item.type === 'example' && (
                          <span className="text-xs font-semibold text-gray-500 uppercase">Example</span>
                        )}
                      </div>
                      <p className="text-xs text-gray-500 truncate">
                        {item.description || 'No description'}
                      </p>
                    </div>
                    <ArrowRight size={16} className="text-gray-500 opacity-0 group-hover:opacity-100 -translate-x-2 group-hover:translate-x-0 transition-all" />
                  </div>
                );
              })}
            </div>
          ) : (
            <div className="py-12 text-center text-gray-500">
              <p>No projects found matching "{query}"</p>
            </div>
          )}
        </div>
      </div>
    </div>
  );
};

export default function ProjectsView({
  backendUrl,
  apiKey,
  onProjectSelect
}: {
  backendUrl: string
  apiKey?: string
  onProjectSelect?: (projectId: string) => void
}) {
  const [activeTab, setActiveTab] = useState('My Projects');
  const [showWizard, setShowWizard] = useState(false);
  const [showSearch, setShowSearch] = useState(false);
  const [projects, setProjects] = useState<any[]>([]);
  const [exampleProjects, setExampleProjects] = useState<any[]>([]);
  const [isLoadingExamples, setIsLoadingExamples] = useState(false);

  // Map icon names to components
  const iconMap: Record<string, React.ElementType> = {
    BookOpen,
    Briefcase,
    StickyNote,
    Apple,
    FolderKanban
  };

  // Define the examples grid to reuse it
  const ExamplesGrid = () => (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
      {exampleProjects.map((example) => {
        const IconComponent = iconMap[example.icon] || FolderKanban;
        return (
          <ProjectCard
            key={example.id}
            icon={IconComponent}
            iconColor={example.icon_color || 'text-blue-400'}
            title={example.name}
            type="Example"
            description={example.description}
            onClick={() => handleCreateFromExample(example.id)}
          />
        );
      })}
    </div>
  );

  const handleCreateFromExample = async (exampleId: string) => {
    try {
      const headers: Record<string, string> = {};
      if (apiKey) {
        headers['x-api-key'] = apiKey;
      }

      const response = await fetch(`${backendUrl}/projects/from-example/${exampleId}`, {
        method: 'POST',
        headers
      });

      if (response.ok) {
        const result = await response.json();
        setProjects([result.project, ...projects]);
        // Switch to My Projects tab to show the newly created project
        setActiveTab('My Projects');
        // Optionally select the project immediately
        onProjectSelect?.(result.project.id);
      } else {
        console.error('Failed to create project from example');
      }
    } catch (error) {
      console.error('Error creating project from example:', error);
    }
  };

  const uploadFilesToProject = async (projectId: string, files: File[]) => {
    const headers: Record<string, string> = {};
    if (apiKey) {
      headers['x-api-key'] = apiKey;
    }

    for (const file of files) {
      try {
        const formData = new FormData();
        formData.append('file', file);

        const response = await fetch(`${backendUrl}/projects/${projectId}/upload`, {
          method: 'POST',
          headers,
          body: formData
        });

        if (!response.ok) {
          console.error(`Failed to upload file: ${file.name}`);
        }
      } catch (error) {
        console.error(`Error uploading file ${file.name}:`, error);
      }
    }
  };

  const handleSaveProject = async (projectData: any) => {
    try {
      const headers: Record<string, string> = {
        'Content-Type': 'application/json'
      };
      if (apiKey) {
        headers['x-api-key'] = apiKey;
      }

      // Extract files before sending
      const files = projectData.files || [];
      const projectDataWithoutFiles = {
        ...projectData,
        files: files.map((f: any) => ({ name: f.name, size: f.size }))
      };

      const response = await fetch(`${backendUrl}/projects`, {
        method: 'POST',
        headers,
        body: JSON.stringify(projectDataWithoutFiles)
      });

      if (response.ok) {
        const result = await response.json();
        setProjects([result.project, ...projects]);
        setShowWizard(false);

        // Upload files if any
        const actualFiles = files.filter((f: any) => f.file).map((f: any) => f.file);
        if (actualFiles.length > 0) {
          await uploadFilesToProject(result.project.id, actualFiles);
        }

        // Auto-select the newly created project
        onProjectSelect?.(result.project.id);
      } else {
        console.error('Failed to create project');
      }
    } catch (error) {
      console.error('Error creating project:', error);
    }
  };

  // Load projects on mount
  React.useEffect(() => {
    const loadProjects = async () => {
      try {
        const headers: Record<string, string> = {};
        if (apiKey) {
          headers['x-api-key'] = apiKey;
        }

        const response = await fetch(`${backendUrl}/projects`, { headers });
        if (response.ok) {
          const result = await response.json();
          setProjects(result.projects || []);
        }
      } catch (error) {
        console.error('Error loading projects:', error);
      }
    };
    loadProjects();
  }, [backendUrl, apiKey]);

  // Load example projects on mount
  React.useEffect(() => {
    const loadExamples = async () => {
      setIsLoadingExamples(true);
      try {
        const headers: Record<string, string> = {};
        if (apiKey) {
          headers['x-api-key'] = apiKey;
        }

        const response = await fetch(`${backendUrl}/projects/examples`, { headers });
        if (response.ok) {
          const result = await response.json();
          setExampleProjects(result.examples || []);
        }
      } catch (error) {
        console.error('Error loading example projects:', error);
      } finally {
        setIsLoadingExamples(false);
      }
    };
    loadExamples();
  }, [backendUrl, apiKey]);

  return (
    <div className="min-h-screen bg-[#1e1f22] text-gray-200 font-sans selection:bg-blue-500/30">

      {/* Top Gradient Fade */}
      <div className="fixed top-0 left-0 right-0 h-16 bg-gradient-to-b from-[#1e1f22] to-transparent z-10 pointer-events-none" />

      {/* Modals */}
      {showWizard && <ProjectWizard onClose={() => setShowWizard(false)} onSave={handleSaveProject} />}
      {showSearch && (
        <SearchModal
          onClose={() => setShowSearch(false)}
          projects={projects}
          exampleProjects={exampleProjects}
          onSelectProject={onProjectSelect}
          onCreateFromExample={handleCreateFromExample}
        />
      )}

      {/* Main Content Container */}
      <main className="px-4 sm:px-8 pt-16 pb-8 max-w-5xl mx-auto w-full">

        {/* Page Header */}
        <div className="flex justify-between items-center mb-6">
          <h1 className="text-2xl font-semibold text-white flex items-center gap-2">
            Projects
          </h1>

          <div className="flex items-center gap-3">
            {/* Search Button */}
            <button
              onClick={() => setShowSearch(true)}
              className="p-2 text-gray-400 hover:text-white hover:bg-[#2b2d31] rounded-xl transition-colors"
              title="Search projects (Ctrl+K)"
            >
              <Search size={20} />
            </button>

            <button
              onClick={() => setShowWizard(true)}
              className="flex items-center gap-2 px-4 py-2 bg-transparent border border-[#383a40] hover:bg-[#2b2d31] text-white rounded-xl text-sm font-medium transition-colors"
            >
              <Plus size={16} />
              <span className="hidden sm:inline">Create project</span>
            </button>
          </div>
        </div>

        {/* Tabs */}
        <div className="flex flex-col gap-6">
          <div className="flex items-center border-b border-[#383a40]">
            <TabButton
              label="My Projects"
              active={activeTab === 'My Projects'}
              onClick={() => setActiveTab('My Projects')}
            />
            <TabButton
              label="Shared with me"
              active={activeTab === 'Shared'}
              onClick={() => setActiveTab('Shared')}
            />
            <TabButton
              label="Examples"
              active={activeTab === 'Examples'}
              onClick={() => setActiveTab('Examples')}
            />
          </div>

          {/* Tab Content */}
          <div className="flex flex-col gap-6 animate-in fade-in duration-300">

            {activeTab === 'My Projects' && (
              <>
                {projects.length === 0 ? (
                  <div className="flex flex-col items-center justify-center p-8 gap-4 border border-[#383a40] rounded-2xl bg-[#1e1f22]/50">
                    <div className="w-12 h-12 rounded-full bg-[#2b2d31] flex items-center justify-center text-gray-400">
                      <FolderKanban size={24} />
                    </div>
                    <div className="text-center max-w-sm">
                      <h2 className="text-base font-semibold text-white mb-1">Get started by creating a new project</h2>
                      <p className="text-sm text-gray-400">
                        Projects help you set custom instructions, attach files, and create specialized AI assistants.
                      </p>
                    </div>
                    <button
                      onClick={() => setShowWizard(true)}
                      className="flex items-center gap-2 px-4 py-2 mt-2 bg-transparent border border-[#383a40] hover:bg-[#2b2d31] text-white rounded-xl text-sm font-medium transition-colors"
                    >
                      <Plus size={16} />
                      New project
                    </button>
                  </div>
                ) : (
                  <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                    {projects.map((project) => (
                      <ProjectCard
                        key={project.id}
                        icon={FolderKanban}
                        iconColor="text-blue-400"
                        title={project.name}
                        type={project.project_type || 'Chat'}
                        description={project.description || 'No description'}
                        onClick={() => onProjectSelect?.(project.id)}
                      />
                    ))}
                  </div>
                )}

                {/* Show examples below My Projects */}
                {projects.length > 0 && exampleProjects.length > 0 && (
                  <>
                    <div className="text-xs font-semibold text-gray-500 uppercase mt-8">Example Templates</div>
                    <ExamplesGrid />
                  </>
                )}
              </>
            )}

            {activeTab === 'Shared' && (
              <div className="flex flex-col items-center justify-center py-20 text-gray-500">
                <p>No projects have been shared with you yet.</p>
              </div>
            )}

            {activeTab === 'Examples' && (
              <ExamplesGrid />
            )}

          </div>
        </div>
      </main>
    </div>
  );
}
